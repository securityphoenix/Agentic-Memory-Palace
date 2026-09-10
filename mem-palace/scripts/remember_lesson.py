#!/usr/bin/env python3
"""
Create a lesson-learned markdown entry from explicit incident details and
synchronize lesson indexes.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LESSONS_DIR = ROOT / "docs" / "knowledge" / "lesson-learned"
LESSON_INDEX = LESSONS_DIR / "index.md"
KNOWLEDGE_INDEX = ROOT / "docs" / "knowledge" / "index.md"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "lesson"


def load_details(details_file: str | None) -> str:
    if not details_file or details_file == "-":
        import sys

        return sys.stdin.read().strip()
    return Path(details_file).read_text(encoding="utf-8").strip()


def ensure_lesson_index() -> None:
    if LESSON_INDEX.exists():
        return
    LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    LESSON_INDEX.write_text(
        "# Lesson Learned Index\n\n"
        "Post-incident writeups. Each entry captures: symptom, root cause, fix, and prevention rule.\n\n"
        "| Lesson | Date | Tags |\n"
        "|--------|------|------|\n\n"
        "## Related\n\n"
        "- Rules derived from lessons live in `.claude/rules/`.\n"
        "- Knowledge graph: [../index.md](../index.md)\n",
        encoding="utf-8",
    )


def update_lesson_index(title: str, slug: str, date_str: str, tags_csv: str) -> None:
    ensure_lesson_index()
    text = LESSON_INDEX.read_text(encoding="utf-8")
    row = f"| [{title}]({slug}.md) | {date_str} | {tags_csv or 'n/a'} |"
    if row in text:
        return
    marker = "## Related"
    if marker in text:
        text = text.replace(marker, f"{row}\n\n{marker}", 1)
    else:
        text += f"\n{row}\n"
    LESSON_INDEX.write_text(text, encoding="utf-8")


def ensure_knowledge_index_link() -> None:
    if not KNOWLEDGE_INDEX.exists():
        return
    text = KNOWLEDGE_INDEX.read_text(encoding="utf-8")
    link_line = "## Lesson Learned\n\n- [Lesson Learned Index](lesson-learned/index.md)\n"
    if "Lesson Learned Index](lesson-learned/index.md)" in text:
        return
    insert_after = "|---------|---------|---------------|---------|"
    if insert_after in text:
        text = text.replace(insert_after, f"{insert_after}\n\n{link_line}", 1)
    else:
        text = f"{text.rstrip()}\n\n{link_line}\n"
    KNOWLEDGE_INDEX.write_text(text, encoding="utf-8")


def build_lesson_markdown(
    title: str,
    date_str: str,
    tags_csv: str,
    severity: str,
    recurrence: str,
    source: str,
    details: str,
) -> str:
    tags = ", ".join([t.strip() for t in tags_csv.split(",") if t.strip()]) if tags_csv else ""
    tags_arr = f"[{tags}]" if tags else "[]"
    return (
        f"---\n"
        f"title: {title}\n"
        f"date: {date_str}\n"
        f"tags: {tags_arr}\n"
        f"severity: {severity}\n"
        f"recurrence: {recurrence}\n"
        f"source: {source}\n"
        f"---\n\n"
        f"# Lesson Learned — {title}\n\n"
        f"## Incident Capture\n\n"
        f"Captured on {date_str} from {source}.\n\n"
        f"## Full Details\n\n"
        f"{details.strip()}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a lesson learned entry and sync indexes.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--tags", default="")
    parser.add_argument("--severity", default="medium")
    parser.add_argument("--recurrence", default="unknown")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--details-file", default="-")
    parser.add_argument("--slug", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    details = load_details(args.details_file)
    if not details:
        raise SystemExit("ERROR: details are empty. Provide --details-file or stdin.")

    date_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    slug = args.slug or slugify(args.title)
    LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    lesson_path = LESSONS_DIR / f"{slug}.md"
    if lesson_path.exists() and not args.force:
        raise SystemExit(
            f"ERROR: {lesson_path} already exists. Use --force to overwrite or provide --slug."
        )

    lesson_md = build_lesson_markdown(
        title=args.title,
        date_str=date_str,
        tags_csv=args.tags,
        severity=args.severity,
        recurrence=args.recurrence,
        source=args.source,
        details=details,
    )
    lesson_path.write_text(lesson_md, encoding="utf-8")

    update_lesson_index(args.title, slug, date_str, args.tags)
    ensure_knowledge_index_link()

    print(f"created: {lesson_path}")
    print(f"updated: {LESSON_INDEX}")
    if KNOWLEDGE_INDEX.exists():
        print(f"updated: {KNOWLEDGE_INDEX}")


if __name__ == "__main__":
    main()
