"""
Dream worker - extracts repeated corrections into portable memory lessons.

This is intentionally tool-neutral. It writes to docs/knowledge/dreams/global.md
instead of mutating Claude, Cursor, or Codex rule files. SessionStart injects
that file for all adapters, so the lesson becomes active without duplicating
rules across editors.

Usage:
    uv run python scripts/dream.py
    uv run python scripts/dream.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from config import DAILY_DIR, KNOWLEDGE_DIR, LOG_FILE, SCRIPTS_DIR, now_iso
from scan_sensitive_data import SensitiveDataError, assert_text_safe

ROOT_DIR = Path(__file__).resolve().parent.parent
DREAMS_DIR = KNOWLEDGE_DIR / "dreams"
DREAM_GLOBAL_FILE = DREAMS_DIR / "global.md"
DREAM_STATE_FILE = SCRIPTS_DIR / "dream-state.json"
MAX_LOGS = 20


def _load_state() -> dict:
    if DREAM_STATE_FILE.exists():
        try:
            return json.loads(DREAM_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict) -> None:
    DREAM_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _recent_daily_logs() -> list[Path]:
    if not DAILY_DIR.exists():
        return []
    return sorted(DAILY_DIR.glob("*.md"))[-MAX_LOGS:]


def _read_recent_logs() -> str:
    parts: list[str] = []
    for path in _recent_daily_logs():
        content = path.read_text(encoding="utf-8")
        parts.append(f"## daily/{path.name}\n\n{content[-8_000:]}")
    return "\n\n---\n\n".join(parts)


async def run_dream(dry_run: bool = False) -> str:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    DREAMS_DIR.mkdir(parents=True, exist_ok=True)
    existing = DREAM_GLOBAL_FILE.read_text(encoding="utf-8") if DREAM_GLOBAL_FILE.exists() else ""
    recent_logs = _read_recent_logs()

    if not recent_logs.strip():
        return "No daily logs found. Nothing to dream."

    try:
        assert_text_safe(existing, source=str(DREAM_GLOBAL_FILE))
        assert_text_safe(recent_logs, source="dream-input:recent-daily-logs")
    except SensitiveDataError as e:
        return f"Dream skipped because sensitive data was detected before LLM processing:\n{e}"

    mode = "Return proposed additions only. Do not write files."
    write_instructions = "Return only the new lesson lines to add to docs/knowledge/dreams/global.md, or DREAM_OK if no new lessons are needed."

    prompt = f"""You are the memory compiler dream worker.

Analyze recent daily logs and extract repeated user corrections into concise
rules that prevent recurring mistakes. Keep the current portable memory design:
write lessons into docs/knowledge/dreams/global.md, not editor-specific rule
files, unless the user explicitly asks for editor-specific rules.

## Existing Dream Lessons

{existing if existing.strip() else "(none)"}

## Recent Daily Logs

{recent_logs}

## Rules

- One correction in one session is noise.
- The same correction pattern in 2+ sessions is a lesson.
- Write one-line rules only.
- Be specific and operational.
- Do not duplicate existing lessons.
- Max 5 new lessons per run.
- Preserve all existing lessons.
- {mode}
- Do not include secrets, tokens, credentials, account IDs, or private URLs.

## Where to Write

{write_instructions}

Good lesson: "Never use em dashes in user-facing prose; use commas or shorter sentences instead."
Bad lesson: "Be more careful with writing."
"""

    answer = ""
    cost = 0.0
    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT_DIR),
                system_prompt={"type": "preset", "preset": "claude_code"},
                allowed_tools=[],
                permission_mode="default",
                max_turns=12,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        answer += block.text
            elif isinstance(message, ResultMessage):
                cost = message.total_cost_usd or 0.0
    except Exception as e:
        return f"Dream failed: {type(e).__name__}: {e}"

    if answer.strip() and "DREAM_OK" not in answer:
        try:
            assert_text_safe(answer, source="dream-output")
        except SensitiveDataError as e:
            return f"Dream skipped because sensitive data was detected in generated lessons:\n{e}"

    if not dry_run and answer.strip() and "DREAM_OK" not in answer:
        normalized = "\n".join(line.rstrip() for line in answer.strip().splitlines() if line.strip())
        if normalized:
            DREAMS_DIR.mkdir(parents=True, exist_ok=True)
            prefix = "" if existing.endswith("\n") or not existing else "\n"
            with DREAM_GLOBAL_FILE.open("a", encoding="utf-8") as handle:
                if not existing.strip():
                    handle.write("# Global Dream Lessons\n\n")
                handle.write(f"{prefix}{normalized}\n")
            with LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(f"{now_iso()} dream wrote {len(normalized.splitlines())} lesson line(s)\n")

    state = _load_state()
    state["last_dream_at"] = now_iso()
    state["last_cost_usd"] = cost
    state["last_log_count"] = len(_recent_daily_logs())
    _save_state(state)

    return answer or f"Dream complete. Cost: ${cost:.4f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract repeated corrections into portable lessons")
    parser.add_argument("--dry-run", action="store_true", help="Preview proposed lessons without writing files")
    args = parser.parse_args()

    print(asyncio.run(run_dream(dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
