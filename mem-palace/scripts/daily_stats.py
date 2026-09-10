"""
Daily stats aggregator — reads today's daily log + state.json to produce a concise stats block.

Can be imported or run standalone:
    uv run python daily-stats.py          # prints stats block to stdout
    uv run python daily-stats.py --json   # prints raw stats as JSON
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # mem comp/
PROJECT_ROOT = ROOT.parent                                  # repo root
DOCS_DIR = PROJECT_ROOT / "docs"
DAILY_DIR = DOCS_DIR / "daily"
KNOWLEDGE_DIR = DOCS_DIR / "knowledge"
SCRIPTS_DIR = ROOT / "scripts"
STATE_FILE = SCRIPTS_DIR / "state.json"


def get_today_log_path() -> Path | None:
    today = datetime.now(timezone.utc).astimezone()
    p = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"
    return p if p.exists() else None


def count_sessions(log_text: str) -> int:
    """Count ## Session or ### Session blocks (flush entries) in the daily log."""
    return len(re.findall(r"^### Session \(", log_text, re.MULTILINE))


def count_decisions(log_text: str) -> int:
    """Count bullet points under 'Decisions Made' sections."""
    decisions = 0
    in_decisions = False
    for line in log_text.splitlines():
        if "**Decisions Made:**" in line or "## Decisions" in line:
            in_decisions = True
        elif line.startswith("**") and in_decisions:
            in_decisions = False
        elif in_decisions and line.strip().startswith("- "):
            decisions += 1
    return decisions


def count_action_items(log_text: str) -> int:
    """Count bullet points under 'Action Items' sections."""
    actions = 0
    in_actions = False
    for line in log_text.splitlines():
        if "**Action Items:**" in line or "## Action Items" in line:
            in_actions = True
        elif line.startswith("**") and in_actions:
            in_actions = False
        elif in_actions and line.strip().startswith("- "):
            actions += 1
    return actions


def count_articles() -> int:
    """Count compiled knowledge articles from state.json."""
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            # Count articles in knowledge/ dir
            concepts = list((KNOWLEDGE_DIR / "concepts").glob("*.md")) if (KNOWLEDGE_DIR / "concepts").exists() else []
            connections = list((KNOWLEDGE_DIR / "connections").glob("*.md")) if (KNOWLEDGE_DIR / "connections").exists() else []
            return len(concepts) + len(connections)
        except (json.JSONDecodeError, OSError):
            pass
    return 0


def get_stats() -> dict:
    """Return stats as a dict."""
    today = datetime.now(timezone.utc).astimezone()
    log_path = get_today_log_path()
    log_text = log_path.read_text(encoding="utf-8") if log_path else ""

    return {
        "date": today.strftime("%Y-%m-%d"),
        "sessions_captured": count_sessions(log_text),
        "decisions_recorded": count_decisions(log_text),
        "articles_compiled": count_articles(),
        "pending_action_items": count_action_items(log_text),
    }


def format_stats_block(stats: dict) -> str:
    return (
        f"## Today's Stats ({stats['date']})\n"
        f"- Sessions captured: {stats['sessions_captured']}\n"
        f"- Decisions recorded: {stats['decisions_recorded']}\n"
        f"- Articles compiled: {stats['articles_compiled']}\n"
        f"- Pending action items: {stats['pending_action_items']}\n"
    )


def main():
    stats = get_stats()
    if "--json" in sys.argv:
        print(json.dumps(stats, indent=2))
    else:
        print(format_stats_block(stats))


if __name__ == "__main__":
    main()
