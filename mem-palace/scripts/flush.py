"""
Memory flush agent - extracts important knowledge from conversation context.

Spawned by session-end.py or pre-compact.py as a background process. Reads
pre-extracted conversation context from a .md file, uses the Claude Agent SDK
to decide what's worth saving, and appends the result to today's daily log.

Usage:
    uv run python flush.py <context_file.md> <session_id>
"""

from __future__ import annotations

# Recursion prevention: set this BEFORE any imports that might trigger Claude
import os
os.environ["CLAUDE_INVOKED_BY"] = "memory_flush"

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scan_sensitive_data import SensitiveDataError, assert_text_safe

ROOT = Path(__file__).resolve().parent.parent              # mem comp/
PROJECT_ROOT = ROOT.parent                                  # repo root
DAILY_DIR = PROJECT_ROOT / "docs" / "daily"
SCRIPTS_DIR = ROOT / "scripts"
STATE_FILE = SCRIPTS_DIR / "last-flush.json"
LOG_FILE = SCRIPTS_DIR / "flush.log"

# Set up file-based logging so we can verify the background process ran.
# The parent process sends stdout/stderr to DEVNULL (to avoid the inherited
# file handle bug on Windows), so this is our only observability channel.
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def load_flush_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_flush_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def append_to_daily_log(content: str, section: str = "Session") -> None:
    """Append content to today's daily log."""
    today = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"

    if not log_path.exists():
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# Daily Log: {today.strftime('%Y-%m-%d')}\n\n## Sessions\n\n## Memory Maintenance\n\n",
            encoding="utf-8",
        )

    time_str = today.strftime("%H:%M")
    entry = f"### {section} ({time_str})\n\n{content}\n\n"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


async def run_flush(context: str) -> str:
    """Use Claude Agent SDK to extract important knowledge from conversation context."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    prompt = f"""Review the conversation context below and respond with a concise summary
of important items that should be preserved in the daily log.
Do NOT use any tools — just return plain text.

Format your response as a structured daily log entry with these sections:

**Context:** [One line about what the user was working on]

**Key Exchanges:**
- [Important Q&A or discussions]

**Decisions Made:**
- [Any decisions with rationale]

**Lessons Learned:**
- [Gotchas, patterns, or insights discovered]

**Action Items:**
- [Follow-ups or TODOs mentioned]

Skip anything that is:
- Routine tool calls or file reads
- Content that's trivial or obvious
- Trivial back-and-forth or clarification exchanges

Only include sections that have actual content. If nothing is worth saving,
respond with exactly: FLUSH_OK

## Conversation Context

{context}"""

    response = ""

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT),
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
            elif isinstance(message, ResultMessage):
                pass
    except Exception as e:
        import traceback
        logging.error("Agent SDK error: %s\n%s", e, traceback.format_exc())
        response = f"FLUSH_ERROR: {type(e).__name__}: {e}"

    return response


COMPILE_AFTER_HOUR = 18  # 6 PM local time
DREAM_ENABLED = os.environ.get("MEM_COMP_DREAM_ENABLED", "").lower() in ("1", "true", "yes")
DREAM_COOLDOWN_SECONDS = 4 * 60 * 60
DREAM_MIN_DAILY_LOGS = 3


def maybe_trigger_compilation() -> None:
    """If it's past the compile hour and today's log hasn't been compiled, run compile.py."""
    import subprocess as _sp

    now = datetime.now(timezone.utc).astimezone()
    if now.hour < COMPILE_AFTER_HOUR:
        return

    # Check if today's log has already been compiled
    today_log = f"{now.strftime('%Y-%m-%d')}.md"
    compile_state_file = SCRIPTS_DIR / "state.json"
    if compile_state_file.exists():
        try:
            compile_state = json.loads(compile_state_file.read_text(encoding="utf-8"))
            ingested = compile_state.get("ingested", {})
            if today_log in ingested:
                # Already compiled today - check if the log has changed since
                from hashlib import sha256
                log_path = DAILY_DIR / today_log
                if log_path.exists():
                    current_hash = sha256(log_path.read_bytes()).hexdigest()[:16]
                    if ingested[today_log].get("hash") == current_hash:
                        return  # log unchanged since last compile
        except (json.JSONDecodeError, OSError):
            pass

    compile_script = SCRIPTS_DIR / "compile.py"
    if not compile_script.exists():
        return

    logging.info("End-of-day compilation triggered (after %d:00)", COMPILE_AFTER_HOUR)

    cmd = ["uv", "run", "--directory", str(ROOT), "python", str(compile_script)]

    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    try:
        log_handle = open(str(SCRIPTS_DIR / "compile.log"), "a")
        _sp.Popen(cmd, stdout=log_handle, stderr=_sp.STDOUT, cwd=str(ROOT), **kwargs)
    except Exception as e:
        logging.error("Failed to spawn compile.py: %s", e)

    # Trigger daily Slack summary after compilation
    maybe_trigger_notify()


def maybe_trigger_notify() -> None:
    """Spawn notify.py in the background to post a daily Slack summary."""
    import subprocess as _sp

    notify_script = SCRIPTS_DIR / "notify.py"
    if not notify_script.exists():
        return

    # Check last-notify state to avoid double-posting
    last_notify_file = SCRIPTS_DIR / "last-notify.json"
    if last_notify_file.exists():
        try:
            notify_state = json.loads(last_notify_file.read_text(encoding="utf-8"))
            today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
            if notify_state.get("last_notified_date") == today:
                logging.info("Daily Slack summary already sent today, skipping")
                return
        except (json.JSONDecodeError, OSError):
            pass

    logging.info("Triggering daily Slack summary")

    cmd = ["uv", "run", "--directory", str(ROOT), "python", str(notify_script)]

    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    try:
        log_handle = open(str(SCRIPTS_DIR / "flush.log"), "a")
        _sp.Popen(cmd, stdout=log_handle, stderr=_sp.STDOUT, cwd=str(ROOT), **kwargs)
    except Exception as e:
        logging.error("Failed to spawn notify.py: %s", e)


def maybe_trigger_dream() -> None:
    """Optionally run the portable dream worker after enough session signal."""
    if not DREAM_ENABLED:
        return

    import subprocess as _sp

    daily_logs = sorted(DAILY_DIR.glob("*.md")) if DAILY_DIR.exists() else []
    if len(daily_logs) < DREAM_MIN_DAILY_LOGS:
        return

    state_file = SCRIPTS_DIR / "dream-state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            last = datetime.fromisoformat(state.get("last_dream_at", "1970-01-01T00:00:00+00:00")).timestamp()
            if time.time() - last < DREAM_COOLDOWN_SECONDS:
                return
        except (ValueError, json.JSONDecodeError, OSError):
            pass

    dream_script = SCRIPTS_DIR / "dream.py"
    if not dream_script.exists():
        return

    logging.info("Triggering portable dream worker")
    cmd = ["uv", "run", "--directory", str(ROOT), "python", str(dream_script)]
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    try:
        log_handle = open(str(SCRIPTS_DIR / "dream.log"), "a")
        _sp.Popen(cmd, stdout=log_handle, stderr=_sp.STDOUT, cwd=str(ROOT), **kwargs)
    except Exception as e:
        logging.error("Failed to spawn dream.py: %s", e)


def main():
    if len(sys.argv) < 3:
        logging.error("Usage: %s <context_file.md> <session_id>", sys.argv[0])
        sys.exit(1)

    context_file = Path(sys.argv[1])
    session_id = sys.argv[2]

    logging.info("flush.py started for session %s, context: %s", session_id, context_file)

    if not context_file.exists():
        logging.error("Context file not found: %s", context_file)
        return

    # Deduplication: skip if same session was flushed within 60 seconds
    state = load_flush_state()
    if (
        state.get("session_id") == session_id
        and time.time() - state.get("timestamp", 0) < 60
    ):
        logging.info("Skipping duplicate flush for session %s", session_id)
        context_file.unlink(missing_ok=True)
        return

    # Read pre-extracted context
    context = context_file.read_text(encoding="utf-8").strip()
    if not context:
        logging.info("Context file is empty, skipping")
        context_file.unlink(missing_ok=True)
        return

    try:
        assert_text_safe(context, source=f"flush-input:{context_file.name}")
    except SensitiveDataError as e:
        logging.error("Skipping flush because sensitive data was detected in input:\n%s", e)
        append_to_daily_log(
            "Sensitive data detected in session context. Memory flush skipped without persisting captured content.",
            "Memory Flush",
        )
        context_file.unlink(missing_ok=True)
        return

    logging.info("Flushing session %s: %d chars", session_id, len(context))

    # Run the LLM extraction
    response = asyncio.run(run_flush(context))

    if response and "FLUSH_ERROR" not in response and "FLUSH_OK" not in response:
        try:
            assert_text_safe(response, source=f"flush-output:{session_id}")
        except SensitiveDataError as e:
            logging.error("Skipping flush output because sensitive data was detected:\n%s", e)
            append_to_daily_log(
                "Sensitive data detected in generated memory summary. Memory flush skipped without persisting generated content.",
                "Memory Flush",
            )
            context_file.unlink(missing_ok=True)
            save_flush_state({"session_id": session_id, "timestamp": time.time(), "skipped": "sensitive-output"})
            return

    # Append to daily log
    if "FLUSH_OK" in response:
        logging.info("Result: FLUSH_OK")
        append_to_daily_log(
            "FLUSH_OK - Nothing worth saving from this session", "Memory Flush"
        )
    elif "FLUSH_ERROR" in response:
        logging.error("Result: %s", response)
        append_to_daily_log(response, "Memory Flush")
    else:
        logging.info("Result: saved to daily log (%d chars)", len(response))
        append_to_daily_log(response, "Session")

    # Update dedup state
    save_flush_state({"session_id": session_id, "timestamp": time.time()})

    # Clean up context file
    context_file.unlink(missing_ok=True)

    # Sync session summaries into knowledge/index.md so session-start
    # always has an up-to-date session log on next launch.
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from sync_session_index import sync as sync_sessions  # type: ignore
        count = sync_sessions()
        logging.info("Session index synced: %d entries", count)
    except Exception as e:
        logging.warning("Session index sync failed (non-fatal): %s", e)

    # End-of-day auto-compilation: if it's past the compile hour and today's
    # log hasn't been compiled yet, trigger compile.py in the background.
    maybe_trigger_compilation()

    # Optional self-evolving lessons. Disabled by default; enable with
    # MEM_COMP_DREAM_ENABLED=1 after reviewing the behavior on your project.
    maybe_trigger_dream()

    logging.info("Flush complete for session %s", session_id)


if __name__ == "__main__":
    main()
