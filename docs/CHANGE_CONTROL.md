# Change Control

How Memory Palace is versioned, released, and upgraded.

This matters more than it does for a normal library, because Memory Palace is **copied
into** a project rather than installed as a dependency. Every install is a fork the moment
it lands. Change control here is about making those copies traceable and upgradable.

---

## 1. Versioning

Memory Palace uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

The version has a specific meaning for this pack. It is a promise about **what an upgrade
does to an existing memory store**.

| Bump | Promise | Examples |
|------|---------|----------|
| **MAJOR** | An existing store needs manual migration. Read the changelog before upgrading. | The daily-log heading contract changes. `docs/knowledge/` gains or renames a directory. A hook's stdin or stdout contract changes. A script is removed or renamed. `AGENTS.md` article frontmatter changes shape. |
| **MINOR** | Drop-in. New capability, existing store untouched. | A new script. A new optional hook. A new lint check. New secret-detection patterns. A new environment variable with a safe default. |
| **PATCH** | Drop-in. Nothing new. | A bug fix. A documentation correction. A tightened regex. A better error message. |

The rule of thumb: **if a user has to do something by hand after upgrading, it is a MAJOR.**

### Where the version lives

| Location | Role |
|----------|------|
| `VERSION` | The single source of truth. One line, no prefix. |
| `mem-palace/pyproject.toml` → `version` | Mirror. Must match `VERSION`. |
| `README.md` version badge | Mirror. Must match `VERSION`. |
| `CHANGELOG.md` | The history, with the reason for each bump. |
| `<project>/mem-palace/INSTALLED_VERSION` | Written by `install.sh`. What that project actually has. |
| `git tag v<version>` | The immutable marker for the release. |

`install.sh --version` prints the pack version. `install.sh <project> --check` compares the
pack against a project's `INSTALLED_VERSION` and reports drift without changing anything.

---

## 2. What is under change control

Not everything in the repo carries the same weight. Three tiers:

### Tier 1 — contracts. A change here is a MAJOR.

These are the interfaces other things depend on.

| Contract | Defined in | Who depends on it |
|----------|-----------|-------------------|
| The daily-log block format (`### Session (HH:MM)`, `**Context:**`, `**Decisions Made:**`, `**Action Items:**`) | `scripts/flush.py` prompt | `sync_session_index.py`, `daily_stats.py`, `compile.py`, `notify.py` |
| The store layout (`docs/daily/`, `docs/knowledge/{concepts,connections,qa,dreams,lesson-learned}/`) | `scripts/config.py` | every script and hook |
| The session-log markers (`<!-- SESSIONS-START -->` / `<!-- SESSIONS-END -->`) | `sync_session_index.py` | `index.md` in every installed store |
| The hook JSON contracts (stdin fields, `hookSpecificOutput` shape) | `hooks/*.py` | Claude Code |
| The recursion guard (`CLAUDE_INVOKED_BY`) | `flush.py`, both capture hooks | anything that spawns Claude Code |
| Article frontmatter and `[[wikilink]]` conventions | `AGENTS.md` | `lint.py`, `query.py`, Obsidian |
| The kit directory name `mem-palace/` and its position at the project root | `config.py`, every hook | the whole path resolution chain |

Changing any of these silently breaks installed stores. If you must, bump MAJOR and write
a migration section in the changelog.

### Tier 2 — behaviour. A change here is a MINOR, or a PATCH if it is a fix.

Prompts, thresholds, constants, lint checks, secret patterns, the installer, the optional
hooks. These change how well the system works, not whether an existing store still parses.

Two exceptions that need care even though they are Tier 2:

- **Secret patterns.** Adding a pattern can start aborting captures that used to succeed.
  Always run `scan_sensitive_data.py` over a real store before releasing a new pattern.
- **The `flush.py` prompt.** It is Tier 2 *only* as long as the five headings survive
  intact. Change the headings and it becomes Tier 1.

### Tier 3 — documentation. Always a PATCH.

`README.md`, this file, `CHANGELOG.md`, code comments.

---

## 3. Release process

Work on a branch. `main` should always be releasable.

```bash
git switch -c change/<short-description>
```

### Before you open a PR

```bash
cd mem-palace

# 1. The scanner must pass — it is the safety gate.
uv run python -m unittest discover -s tests

# 2. Structural lint must be clean. Free, no API calls.
uv run python scripts/lint.py --structural-only

# 3. Both output modes of the injection hook must work.
uv run python hooks/session-start.py | head -3
MEM_COMP_OUTPUT=markdown uv run python hooks/session-start.py | head -20

# 4. Every shell script must parse.
cd .. && bash -n install.sh && bash -n extras/hooks/doc-heal.sh

# 5. Every JSON file must parse.
python3 -c "import json,glob;[json.load(open(f)) for f in glob.glob('templates/*.json')+['mem-palace/sensitive-patterns.json']];print('json ok')"

# 6. A clean install must pass its own verification.
./install.sh /tmp/mp-release-check --extras

# 7. The three version mirrors must agree.
test "$(cat VERSION)" = "$(grep '^version' mem-palace/pyproject.toml | cut -d'"' -f2)" \
  && grep -q "version-$(cat VERSION)-" README.md \
  && echo "version ok"

# 8. Every README image must exist.
for f in $(grep -o 'src="assets/[^"]*"' README.md | cut -d'"' -f2); do test -f "$f" || echo "MISSING $f"; done
```

If you touched a hook or a script that writes to the store, also do an **end-to-end
capture test**: install into a throwaway project, run a real Claude Code session, end it,
and confirm a block appears in `docs/daily/` and a row appears in the session log.
`mem-palace/scripts/flush.log` tells you what actually happened.

### Cutting the release

1. Decide the bump using the table in [section 1](#1-versioning).
2. Update `VERSION`.
3. Update `version` in `mem-palace/pyproject.toml` and the version badge at the top of
   `README.md` to match.
4. If you changed the project name or dependencies, regenerate the lock:
   `cd mem-palace && uv lock`.
5. Move the `## [Unreleased]` entries in `CHANGELOG.md` under a new
   `## [x.y.z] — YYYY-MM-DD` heading. Add a fresh empty `Unreleased`.
6. For a MAJOR, add a **Migration** subsection to that changelog entry with the exact
   commands an existing user must run.
7. Commit, tag, push.

```bash
git commit -am "release: v1.1.0"
git tag -a v1.1.0 -m "v1.1.0"
git push origin main --follow-tags
```

### Never do these

- Never move a tag. Cut a new PATCH instead.
- Never edit a released changelog entry, except to fix a typo.
- Never bump `VERSION` without a changelog entry.
- Never let `VERSION`, `pyproject.toml`, and the README badge disagree. Check with:
  `grep -h 'version' VERSION mem-palace/pyproject.toml <(grep -o 'version-[0-9.]*' README.md)`

---

## 4. Upgrading an installed project

### Check for drift first

```bash
cd /path/to/Agentic-Memory-Palace
git pull
./install.sh /path/to/your/project --check
```

This reports the pack version, the project's `INSTALLED_VERSION`, and whether any installed
file differs from the pack. It changes nothing.

### Then upgrade

```bash
./install.sh /path/to/your/project --extras
```

The installer is safe to re-run:

- It **overwrites** the code — `hooks/`, `scripts/`, `AGENTS.md`, `pyproject.toml`,
  `uv.toml`, `uv.lock`, `sensitive-patterns.json`.
- It **never touches** your memory — `docs/daily/` and `docs/knowledge/` are only created
  if missing.
- It **merges** hook config and **backs up** `settings.json` first.

Read the changelog before a MAJOR upgrade. Follow the Migration section.

### If you customised the pack

The overwrite is the problem. Two options.

**Option A — keep your changes in the pack.** Fork this repo, apply your changes there,
and merge upstream releases into your fork. Then `install.sh` from your fork. This is the
right answer if your changes are permanent.

**Option B — re-apply after each upgrade.** Keep a patch file, and check `--check` output
after every upgrade to see what got reverted. Cheaper up front, and it will bite you.

The files people most often customise, in order: `sensitive-patterns.json`, `AGENTS.md`,
and the threshold constants at the top of the hooks. If that is all you changed, `--check`
will name exactly those files.

### Rollback

```bash
cd /path/to/Agentic-Memory-Palace
git checkout v1.0.0
./install.sh /path/to/your/project --extras
```

Then restore the settings backup the installer made:
`<project>/.claude/settings.json.bak.<timestamp>`.

Your memory store is not versioned by the pack and is unaffected by a rollback. If you
committed `docs/` to git, that is its version control — which is the argument for
committing it.

---

## 5. Reporting a defect

Include these, or the report is not actionable:

1. The pack version: `cat <project>/mem-palace/INSTALLED_VERSION`.
2. The relevant lines from `<project>/mem-palace/scripts/flush.log`.
3. `uv --version`, `python3 --version`, `uname -m`, and your OS.
4. Which hook or script, and the exact command you ran.
5. What you expected, and what happened.

**Never paste a daily log or a knowledge article into an issue** without reading it first.
They contain your conversation content.

For a suspected secret leak — content that reached `docs/` and should not have — do not
open a public issue. Report it privately, and include the rule name that should have
caught it, never the leaked value.
