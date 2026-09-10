"""
SessionStart hook - injects knowledge base context into every conversation.

What Claude receives at session start:
  1. Today's date
  2. Knowledge Base Index — KB articles + Session Log (all past sessions with summaries)
  3. Today's full daily log — complete text of today's session entries
  4. Today's Stats — session count, decisions, articles, action items
  5. Project Doc Index (DOC_INDEX.md) — read-only, first 3000 chars
  6. Dream Lessons — optional repeated-correction rules, if enabled

The index (docs/knowledge/index.md) is the primary retrieval mechanism.
It is kept up-to-date by flush.py after every session via sync_session_index.py.

Configure in .claude/settings.json:
{
    "hooks": {
        "SessionStart": [{
            "matcher": "",
            "command": "uv run python hooks/session-start.py"
        }]
    }
}
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent.parent              # mem comp/
PROJECT_ROOT = ROOT.parent                                  # repo root
DOCS_DIR = PROJECT_ROOT / "docs"                           # repo docs/
KNOWLEDGE_DIR = DOCS_DIR / "knowledge"
DAILY_DIR = DOCS_DIR / "daily"
SCRIPTS_DIR = ROOT / "scripts"
INDEX_FILE = KNOWLEDGE_DIR / "index.md"
DREAMS_DIR = KNOWLEDGE_DIR / "dreams"
DREAM_GLOBAL_FILE = DREAMS_DIR / "global.md"

# DOC_INDEX is read-only, never written
DOC_INDEX_FILE = PROJECT_ROOT / "DOC_INDEX.md"

MAX_CONTEXT_CHARS = 24_000
MAX_TODAY_LOG_CHARS = 4_000   # today's full log — not just last N lines
MAX_DOC_INDEX_CHARS = 3_000
MAX_DREAM_CHARS = 3_000


def ensure_session_index_current() -> None:
    """
    Run sync_session_index inline before reading the index so Claude always
    sees the latest session log. Fast: only file I/O, no API calls.
    """
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from sync_session_index import sync as sync_sessions  # type: ignore
        sync_sessions()
    except Exception:
        pass  # Non-fatal — index may be slightly stale but never crashes the hook


def get_index() -> str:
    """Read knowledge/index.md (KB articles + session log)."""
    if INDEX_FILE.exists():
        return INDEX_FILE.read_text(encoding="utf-8")
    return "(empty — no articles compiled and no sessions flushed yet)"


def get_today_log() -> str:
    """Read today's complete daily log (truncated to MAX_TODAY_LOG_CHARS)."""
    today = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"

    if not log_path.exists():
        return "(no log yet today)"

    content = log_path.read_text(encoding="utf-8")
    if len(content) > MAX_TODAY_LOG_CHARS:
        # Keep the tail (most recent part of today's log)
        content = "...(earlier entries truncated)\n\n" + content[-MAX_TODAY_LOG_CHARS:]
    return content


def get_daily_stats() -> str:
    """Produce today's stats block (no subprocess, inline import)."""
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from daily_stats import get_stats, format_stats_block  # type: ignore
        return format_stats_block(get_stats())
    except Exception:
        today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        return f"## Today's Stats ({today})\n- (stats unavailable)\n"


def get_doc_index() -> str:
    """Read the project DOC_INDEX.md (never written, read-only)."""
    if DOC_INDEX_FILE.exists():
        content = DOC_INDEX_FILE.read_text(encoding="utf-8")
        if len(content) > MAX_DOC_INDEX_CHARS:
            content = content[:MAX_DOC_INDEX_CHARS] + "\n...(truncated)"
        return content
    return "(DOC_INDEX.md not found)"


def get_dream_lessons() -> str:
    """Read portable repeated-correction lessons written by scripts/dream.py."""
    if not DREAM_GLOBAL_FILE.exists():
        return "(no dream lessons captured yet)"
    content = DREAM_GLOBAL_FILE.read_text(encoding="utf-8").strip()
    if len(content) > MAX_DREAM_CHARS:
        content = content[:MAX_DREAM_CHARS] + "\n...(truncated)"
    return content or "(no dream lessons captured yet)"


def build_context() -> str:
    """Assemble the context to inject into the conversation."""
    parts = []

    # 1. Today's date
    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%A, %B %d, %Y')}")

    # 2. Knowledge Base Index (KB articles + session log — the core retrieval doc)
    index_content = get_index()
    parts.append(f"## Knowledge Base Index\n\n{index_content}")

    # 3. Today's full daily log (detail for current day's sessions)
    today_log = get_today_log()
    parts.append(f"## Today's Daily Log\n\n{today_log}")

    # 4. Stats
    stats_block = get_daily_stats()
    parts.append(stats_block)

    # 5. Project doc router (read-only)
    doc_index = get_doc_index()
    parts.append(f"## Project Doc Index (DOC_INDEX.md)\n\n{doc_index}")

    # 6. Optional self-evolving lessons. Stored under docs/knowledge so every
    # editor adapter can read the same source of truth.
    dream_lessons = get_dream_lessons()
    parts.append(f"## Dream Lessons\n\n{dream_lessons}")

    context = "\n\n---\n\n".join(parts)

    # Truncate if too long
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n...(truncated)"

    return context


def main():
    # Keep the index fresh before building context
    ensure_session_index_current()

    context = build_context()

    if os.environ.get("MEM_COMP_OUTPUT", "json").lower() == "markdown":
        print(context)
    else:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(output))


if __name__ == "__main__":
    main()
