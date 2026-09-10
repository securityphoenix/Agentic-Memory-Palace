# Changelog

All notable changes to Memory Palace are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html), with the
compatibility rules defined in [docs/CHANGE_CONTROL.md](docs/CHANGE_CONTROL.md).

The current version is in [VERSION](VERSION). An installed copy records the version it was
installed from in `<project>/mem-palace/INSTALLED_VERSION`.

## [Unreleased]

Nothing yet.

## [1.0.0] — 2026-09-10

First public release. Extracted from a private working system and made portable.

### Added

- **Three core Claude Code hooks** (`mem-palace/hooks/`):
  - `session-start.py` (`SessionStart`) — injects the knowledge index, today's daily log,
    stats, an optional `DOC_INDEX.md`, and dream rules. Local I/O only, no API calls.
  - `session-end.py` (`SessionEnd`) — captures the last 30 turns of the transcript and
    spawns the background extraction worker. Minimum 1 turn.
  - `pre-compact.py` (`PreCompact`) — the same capture before Claude Code auto-compacts,
    so long sessions do not lose detail to summarisation. Minimum 5 turns.
- **Twelve scripts** (`mem-palace/scripts/`): `flush.py`, `compile.py`, `query.py`,
  `lint.py`, `dream.py`, `remember_lesson.py`, `sync_session_index.py`, `daily_stats.py`,
  `scan_sensitive_data.py`, `notify.py`, `config.py`, `utils.py`.
- **The three-layer memory model**: `docs/daily/` as immutable source, `docs/knowledge/`
  as the compiled graph, and `mem-palace/AGENTS.md` as the compiler specification.
- **Three levels of lessons learned**: automatic `**Lessons Learned:**` bullets in the
  daily log, deliberate incident writeups in `docs/knowledge/lesson-learned/`, and
  auto-extracted one-line rules in `docs/knowledge/dreams/global.md`.
- **A sensitive-data gate** (`scan_sensitive_data.py` + `sensitive-patterns.json`). Every
  capture is scanned before the model sees it and again before it is written. Fails
  closed. Findings report source, line, and rule name only — never the matched value.
- **A guided installer** (`install.sh`) with `--extras`, `--dry-run`, `--python`,
  `--version`, and `--check`. Merges hook config rather than overwriting it, backs up an
  existing `settings.json`, and verifies the install before reporting success.
- **Four optional context-hygiene hooks** (`extras/hooks/`): `session-size-warn.py`,
  `drift-check.py`, `prefer-native-search.py`, and a generic `doc-heal.sh`. All
  fail-silent; none can block a prompt or a tool call.
- **Hook config templates** (`templates/settings.core.json`,
  `templates/settings.extras.json`) for manual installation.
- **Documentation**: a detailed `README.md` covering the method, the three memory
  artefacts, installation, and every hook and script; plus
  [docs/CHANGE_CONTROL.md](docs/CHANGE_CONTROL.md).
- **Branding**: a logo hero and a one-page method infographic in `assets/`, referenced
  from `README.md`. Full-resolution sources are kept out of git; `assets/` holds
  web-sized copies.
- **README section 3.4** documents Claude Code's per-agent memory
  (`.claude/agent-memory/<agent>/`) as an adjacent fourth layer the pack does not own,
  with the split between it, the knowledge graph, and `dreams/global.md`.

### Fixed

Two defects found while packaging, both fixed before release.

- `uv.toml` set `python-preference = "only-managed"`, which let `uv` select an interpreter
  built for the wrong CPU architecture. `cryptography` then compiled from source and
  failed without a Rust toolchain and OpenSSL headers. The setting is removed, the reason
  is documented in `uv.toml`, and `install.sh --python <version>` pins an interpreter.
- `install.sh` continued after a failed `uv sync`, because `set -e` does not fire for a
  command on the left of `&&`. The exit status is now captured and checked explicitly,
  with an error that names the likely cause.

### Changed from the private original

- The hardcoded Slack channel ID is now the `MEM_PALACE_SLACK_CHANNEL` environment
  variable. `notify.py` no-ops when it is unset.
- `doc-heal.sh` was rewritten. The original hardcoded one project's class names and doc
  paths; the new one works in any git repo and is configured by `DOC_HEAL_DOC_DIR` and
  `DOC_HEAL_MAX_FILES`.
- Project-specific skip directories were removed from `sensitive-patterns.json`.
- Internal MCP server and tool names were removed from `prefer-native-search.py`.
- Temporary state files use a `mempalace-` prefix instead of a project-specific one.
- The Python package was renamed from `llm-personal-kb` to `memory-palace`, and `uv.lock`
  was regenerated.

### Not included

Hooks from the source project that are not portable were deliberately left out: the
graph-MCP enrichment hooks, the agent-config write gate, and the frontend corpus
governance hooks. They depend on internal MCP servers, internal plan documents, and one
repository's directory layout.

[Unreleased]: https://github.com/securityphoenix/Agentic-Memory-Palace/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/securityphoenix/Agentic-Memory-Palace/releases/tag/v1.0.0
