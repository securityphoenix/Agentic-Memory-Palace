#!/usr/bin/env python3
"""Portable sensitive-data scanner for memory capture artifacts.

This module intentionally lives inside mem-comp so the memory kit can be copied
into another repository without depending on that repository's CI scripts.
It reports only source, line, and rule names; matched secret values are never
included in errors or reports.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MEM_COMP_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = MEM_COMP_ROOT.parent
PATTERNS_PATH = MEM_COMP_ROOT / "sensitive-patterns.json"
ACCOUNT_ID_RE = re.compile(r"\b\d{12}\b")


@dataclass(frozen=True)
class Finding:
    source: str
    line_number: int
    rule: str


class SensitiveDataError(RuntimeError):
    """Raised when content should not be persisted to memory."""

    def __init__(self, findings: list[Finding]):
        self.findings = findings
        super().__init__(format_findings(findings))


def load_patterns(patterns_path: Path = PATTERNS_PATH) -> dict:
    with patterns_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("known_account_ids", [])
    data.setdefault("anonymized_account_prefix", "")
    data.setdefault("anonymized_account_id_regexes", [])
    data.setdefault("skip_directories", [])
    data.setdefault("skip_extensions", [])
    data.setdefault("allowlist_regexes", [])
    data.setdefault("allowlisted_findings", [])
    data.setdefault("patterns", {})
    return data


def _compile_regexes(patterns_config: dict[str, str]) -> dict[str, re.Pattern[str]]:
    regexes = {}
    for name, pattern in patterns_config.items():
        try:
            regexes[name] = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid regex for {name}: {exc}") from exc
    return regexes


def _compile_allowlist(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise ValueError(f"Invalid allowlist regex {pattern}: {exc}") from exc
    return compiled


def _compile_account_allowlist(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(f"Invalid account id allowlist regex {pattern}: {exc}") from exc
    return compiled


def _build_finding_allowlist(entries: Iterable[dict]) -> set[tuple[str, int, str]]:
    allowlist: set[tuple[str, int, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        line = entry.get("line")
        rule = entry.get("rule")
        if isinstance(path, str) and isinstance(line, int) and isinstance(rule, str):
            allowlist.add((Path(path).as_posix(), line, rule))
    return allowlist


def _looks_placeholder(text: str) -> bool:
    lowered = text.lower()
    placeholders = [
        "your_",
        "example",
        "changeme",
        "placeholder",
        "dummy",
        "redacted",
        "replace_me",
        "todo",
        "<redacted>",
    ]
    return any(token in lowered for token in placeholders)


def _allowlisted(text: str, line: str, allowlist: list[re.Pattern[str]]) -> bool:
    if _looks_placeholder(text):
        return True
    return any(pattern.search(text) or pattern.search(line) for pattern in allowlist)


def _is_account_id_rule(rule_name: str) -> bool:
    return rule_name == "aws_arn_with_real_account" or "account_id" in rule_name


def _is_anonymized_account_id(
    account_id: str,
    allowlist: list[re.Pattern[str]],
    anonymized_prefix: str,
) -> bool:
    if anonymized_prefix and account_id.startswith(anonymized_prefix):
        return True
    return any(pattern.fullmatch(account_id) for pattern in allowlist)


def _should_skip_path(path: Path, config: dict, include_anonymized: bool) -> bool:
    if not include_anonymized and any(part in config["skip_directories"] for part in path.parts):
        return True
    if not include_anonymized and any("anonymized" in part for part in path.parts):
        return True
    return path.suffix in config["skip_extensions"]


def _is_binary_file(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:2048]
    except OSError:
        return True
    if not chunk:
        return False
    if b"\0" in chunk:
        return True
    text_chars = sum(1 for b in chunk if 32 <= b < 127 or b in b"\n\r\t\b\f")
    return (text_chars / len(chunk)) < 0.7


def scan_text(
    text: str,
    *,
    source: str = "<memory>",
    config: dict | None = None,
) -> list[Finding]:
    config = config or load_patterns()
    patterns = _compile_regexes(config["patterns"])
    allowlist = _compile_allowlist(config["allowlist_regexes"])
    account_allowlist = _compile_account_allowlist(config["anonymized_account_id_regexes"])
    finding_allowlist = _build_finding_allowlist(config["allowlisted_findings"])
    known_ids = config["known_account_ids"]
    anonymized_prefix = config["anonymized_account_prefix"]
    known_ids_re = re.compile("|".join(re.escape(val) for val in known_ids)) if known_ids else None

    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if known_ids_re and known_ids_re.search(line):
            key = (source, line_number, "known_account_id")
            if key not in finding_allowlist:
                findings.append(Finding(source, line_number, "known_account_id"))

        for name, regex in patterns.items():
            for match in regex.finditer(line):
                match_text = match.group(0)
                if _allowlisted(match_text, line, allowlist):
                    continue
                if (source, line_number, name) in finding_allowlist:
                    continue
                if _is_account_id_rule(name):
                    account_ids = ACCOUNT_ID_RE.findall(match_text)
                    if account_ids and all(
                        _is_anonymized_account_id(account_id, account_allowlist, anonymized_prefix)
                        for account_id in account_ids
                    ):
                        continue
                findings.append(Finding(source, line_number, name))
    return findings


def assert_text_safe(text: str, *, source: str = "<memory>") -> None:
    findings = scan_text(text, source=source)
    if findings:
        raise SensitiveDataError(findings)


def scan_file(path: Path, *, source: str | None = None, config: dict | None = None) -> list[Finding]:
    config = config or load_patterns()
    if _is_binary_file(path):
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    display = source or _display_path(path)
    return scan_text(text, source=display, config=config)


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def iter_files(paths: Iterable[Path], *, include_anonymized: bool = False) -> Iterable[Path]:
    config = load_patterns()
    for path in paths:
        resolved = path if path.is_absolute() else PROJECT_ROOT / path
        if not resolved.exists():
            continue
        if resolved.is_file():
            rel = Path(_display_path(resolved))
            if not _should_skip_path(rel, config, include_anonymized):
                yield resolved
            continue
        if resolved.is_dir():
            for child in sorted(resolved.rglob("*")):
                if not child.is_file():
                    continue
                rel = Path(_display_path(child))
                if _should_skip_path(rel, config, include_anonymized):
                    continue
                yield child


def format_findings(findings: list[Finding]) -> str:
    lines = ["Sensitive data findings:"]
    for finding in findings:
        lines.append(f"- {finding.source}:{finding.line_number} [{finding.rule}]")
    return "\n".join(lines)


def format_summary(findings: list[Finding]) -> str:
    summary: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for finding in findings:
        summary.setdefault(finding.source, set()).add(finding.rule)
        counts[finding.source] = counts.get(finding.source, 0) + 1
    lines = ["Findings by file:"]
    for source in sorted(summary):
        rules = ", ".join(sorted(summary[source]))
        lines.append(f"- {source} ({counts[source]} finding(s), rules: {rules})")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan memory files for sensitive data.")
    parser.add_argument("paths", nargs="*", help="Files or directories to scan relative to the project root.")
    parser.add_argument("--include-anonymized", action="store_true", help="Include anonymized directories.")
    parser.add_argument("--max-findings", type=int, default=0, help="Stop after this many findings.")
    args = parser.parse_args()

    paths = [Path(path) for path in args.paths] if args.paths else [PROJECT_ROOT / "docs" / "daily", PROJECT_ROOT / "docs" / "knowledge"]
    findings: list[Finding] = []
    scanned = 0
    config = load_patterns()
    for path in iter_files(paths, include_anonymized=args.include_anonymized):
        scanned += 1
        findings.extend(scan_file(path, config=config))
        if args.max_findings and len(findings) >= args.max_findings:
            findings = findings[: args.max_findings]
            break

    if findings:
        print("SENSITIVE DATA DETECTED")
        print(format_findings(findings))
        print()
        print(format_summary(findings))
        print(f"\nTotal findings: {len(findings)} in {scanned} file(s).")
        return 1

    print(f"No sensitive data findings in {scanned} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
