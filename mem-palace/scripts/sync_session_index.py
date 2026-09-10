"""
Sync session summaries into knowledge/index.md.

Reads all docs/daily/*.md files in date order, extracts each session entry
(### Session and ### Memory Flush blocks), and writes a compact Session Log
table into knowledge/index.md between <!-- SESSIONS-START --> and
<!-- SESSIONS-END --> markers.

Run automatically by flush.py after each flush.
Run manually:
    uv run python scripts/sync_session_index.py
    uv run python scripts/sync_session_index.py --dry-run
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # mem comp/
PROJECT_ROOT = ROOT.parent                                  # repo root
DOCS_DIR = PROJECT_ROOT / "docs"
DAILY_DIR = DOCS_DIR / "daily"
KNOWLEDGE_DIR = DOCS_DIR / "knowledge"
INDEX_FILE = KNOWLEDGE_DIR / "index.md"

SESSIONS_START = "<!-- SESSIONS-START -->"
SESSIONS_END = "<!-- SESSIONS-END -->"

# Max sessions to keep in the index (most recent N)
MAX_SESSIONS = 60


def parse_daily_log(path: Path) -> list[dict]:
    """
    Parse a daily log file and return a list of session entries.

    Each entry: { date, time, kind, summary }
      kind: "session" | "flush_ok" | "flush_error"
      summary: one-line context string
    """
    date_str = path.stem  # e.g. "2026-04-15"
    text = path.read_text(encoding="utf-8")
    entries = []

    # Match ### Session (HH:MM) or ### Memory Flush (HH:MM)
    block_pattern = re.compile(
        r"^### (Session|Memory Flush) \((\d{2}:\d{2})\)(.*?)(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )

    for match in block_pattern.finditer(text):
        kind_raw = match.group(1)   # "Session" or "Memory Flush"
        time_str = match.group(2)   # "15:51"
        body = match.group(3).strip()

        if kind_raw == "Session":
            # Extract **Context:** line
            ctx_match = re.search(r"\*\*Context:\*\*\s*(.+?)(?:\n|$)", body)
            if ctx_match:
                summary = ctx_match.group(1).strip()
            else:
                # Fall back to first non-empty line
                first_line = next(
                    (ln.strip() for ln in body.splitlines() if ln.strip()), "(no summary)"
                )
                summary = first_line[:120]

            entries.append(
                {"date": date_str, "time": time_str, "kind": "session", "summary": summary}
            )
        else:
            # Memory Flush
            if "FLUSH_OK" in body:
                entries.append(
                    {"date": date_str, "time": time_str, "kind": "flush_ok", "summary": "FLUSH_OK — nothing saved"}
                )
            elif "FLUSH_ERROR" in body:
                entries.append(
                    {"date": date_str, "time": time_str, "kind": "flush_error", "summary": "FLUSH_ERROR"}
                )
            else:
                # Non-trivial flush (actual content)
                ctx_match = re.search(r"\*\*Context:\*\*\s*(.+?)(?:\n|$)", body)
                if ctx_match:
                    summary = ctx_match.group(1).strip()
                else:
                    first_line = next(
                        (ln.strip() for ln in body.splitlines() if ln.strip()), "(saved)"
                    )
                    summary = first_line[:120]
                entries.append(
                    {"date": date_str, "time": time_str, "kind": "session", "summary": summary}
                )

    return entries


def build_sessions_block(all_entries: list[dict]) -> str:
    """Build the markdown sessions block to inject into index.md."""
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    lines = [SESSIONS_START, ""]
    lines.append("## Session Log")
    lines.append("")
    lines.append(f"*{len(all_entries)} sessions captured · last updated {now}*")
    lines.append("")
    lines.append("| Date | Time | Summary |")
    lines.append("|------|------|---------|")

    for entry in all_entries:
        summary = entry["summary"].replace("|", "—")  # escape pipes
        if len(summary) > 120:
            summary = summary[:117] + "..."
        # Dim flush_ok entries
        if entry["kind"] == "flush_ok":
            row = f"| {entry['date']} | {entry['time']} | *(flush ok)* |"
        else:
            row = f"| {entry['date']} | {entry['time']} | {summary} |"
        lines.append(row)

    lines.append("")
    lines.append(SESSIONS_END)
    return "\n".join(lines)


def sync(dry_run: bool = False) -> int:
    """
    Sync session log into knowledge/index.md.
    Returns the number of session entries written.
    """
    if not INDEX_FILE.exists():
        # Bootstrap an empty index
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        INDEX_FILE.write_text(
            "# Knowledge Base Index\n\n"
            "| Article | Summary | Compiled From | Updated |\n"
            "|---------|---------|---------------|---------|\n\n",
            encoding="utf-8",
        )

    # Collect all sessions from all daily logs (sorted by date asc)
    all_entries: list[dict] = []
    for log_path in sorted(DAILY_DIR.glob("*.md")):
        try:
            all_entries.extend(parse_daily_log(log_path))
        except Exception as e:
            print(f"  Warning: could not parse {log_path.name}: {e}")

    # Keep only the most recent MAX_SESSIONS entries
    if len(all_entries) > MAX_SESSIONS:
        all_entries = all_entries[-MAX_SESSIONS:]

    sessions_block = build_sessions_block(all_entries)

    original = INDEX_FILE.read_text(encoding="utf-8")

    if SESSIONS_START in original and SESSIONS_END in original:
        # Replace existing block
        before = original[: original.index(SESSIONS_START)]
        after = original[original.index(SESSIONS_END) + len(SESSIONS_END):]
        updated = before.rstrip() + "\n\n" + sessions_block + after.lstrip()
    else:
        # Append at end
        updated = original.rstrip() + "\n\n" + sessions_block + "\n"

    if dry_run:
        print("=== DRY RUN: would write to knowledge/index.md ===")
        # Show just the sessions block
        print(sessions_block[:2000])
        return len(all_entries)

    INDEX_FILE.write_text(updated, encoding="utf-8")
    return len(all_entries)


def main():
    dry_run = "--dry-run" in sys.argv
    count = sync(dry_run=dry_run)
    label = "[DRY RUN] " if dry_run else ""
    print(f"{label}Session index synced: {count} entries written to knowledge/index.md")


if __name__ == "__main__":
    main()
