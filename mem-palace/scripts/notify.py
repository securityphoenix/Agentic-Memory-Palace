"""
Daily Slack summary notifier.

Spawned by flush.py once per day after compilation. Reads today's daily log
and stats, then posts a compact summary to the Slack channel named in the
MEM_PALACE_SLACK_CHANNEL environment variable, via the Slack MCP tool.

Falls back to a no-op log entry if Slack isn't reachable.

Usage:
    uv run python notify.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # mem comp/
PROJECT_ROOT = ROOT.parent                                  # repo root
SCRIPTS_DIR = ROOT / "scripts"
DAILY_DIR = PROJECT_ROOT / "docs" / "daily"

LOG_FILE = SCRIPTS_DIR / "flush.log"
NOTIFY_STATE_FILE = SCRIPTS_DIR / "last-notify.json"

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Slack channel ID (e.g. "C0123456789"). Unset => notifications are skipped.
SLACK_CHANNEL = os.environ.get("MEM_PALACE_SLACK_CHANNEL", "")


def load_notify_state() -> dict:
    if NOTIFY_STATE_FILE.exists():
        try:
            return json.loads(NOTIFY_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_notify_state(state: dict) -> None:
    NOTIFY_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def already_notified_today() -> bool:
    state = load_notify_state()
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    return state.get("last_notified_date") == today


def get_today_log_excerpt() -> str:
    """Get the most recent session entry from today's log (max 800 chars)."""
    today = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"
    if not log_path.exists():
        return "(no log today)"

    text = log_path.read_text(encoding="utf-8")
    # Find last ### Session block
    import re
    sessions = list(re.finditer(r"^### Session \(", text, re.MULTILINE))
    if not sessions:
        return "(no sessions recorded)"

    last_start = sessions[-1].start()
    excerpt = text[last_start:last_start + 800].strip()
    # Trim to a clean line boundary
    lines = excerpt.splitlines()
    clean = "\n".join(lines[:12])  # max 12 lines
    return clean


def build_slack_message(stats: dict, excerpt: str) -> str:
    return (
        f":bar_chart: *Daily Dev Summary — {stats['date']}*\n"
        f"Sessions: {stats['sessions_captured']}  |  "
        f"Decisions: {stats['decisions_recorded']}  |  "
        f"Action items: {stats['pending_action_items']}  |  "
        f"Articles: {stats['articles_compiled']}\n\n"
        f"*Latest session:*\n```\n{excerpt}\n```"
    )


async def send_slack_message(message: str) -> bool:
    """Try to send message via Claude Agent SDK with Slack MCP tool."""
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        prompt = f"""Send a Slack message to channel {SLACK_CHANNEL} with this exact text (do not modify it):

{message}

Use the slack_send_message tool. If it fails or the tool is unavailable, say "SLACK_UNAVAILABLE"."""

        async for msg in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT),
                allowed_tools=["mcp__claude_ai_Slack__slack_send_message"],
                max_turns=3,
            ),
        ):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and "SLACK_UNAVAILABLE" in block.text:
                        return False
        return True
    except Exception as e:
        logging.error("Slack notify error: %s", e)
        return False


def main():
    if not SLACK_CHANNEL:
        logging.info("notify.py: MEM_PALACE_SLACK_CHANNEL not set, skipping")
        return

    if already_notified_today():
        logging.info("notify.py: already sent today, skipping")
        return

    # Import stats inline to avoid circular import
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from daily_stats import get_stats, format_stats_block  # noqa: F401
        stats = get_stats()
    except ImportError:
        # Fallback: minimal stats
        today = datetime.now(timezone.utc).astimezone()
        stats = {
            "date": today.strftime("%Y-%m-%d"),
            "sessions_captured": 0,
            "decisions_recorded": 0,
            "articles_compiled": 0,
            "pending_action_items": 0,
        }

    excerpt = get_today_log_excerpt()
    message = build_slack_message(stats, excerpt)

    logging.info("notify.py: sending daily summary for %s", stats["date"])
    sent = asyncio.run(send_slack_message(message))

    if sent:
        logging.info("notify.py: Slack message sent")
        today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        save_notify_state({"last_notified_date": today})
    else:
        logging.warning("notify.py: Slack unavailable, message not sent:\n%s", message)


if __name__ == "__main__":
    main()
