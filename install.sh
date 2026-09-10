#!/usr/bin/env bash
#
# Memory Palace installer.
#
# Copies the mem-palace/ kit into a target project, wires the Claude Code hooks,
# creates the memory store, and verifies the install.
#
# Usage:
#   ./install.sh /path/to/your/project              # core memory hooks only
#   ./install.sh /path/to/your/project --extras     # also install context-hygiene hooks
#   ./install.sh /path/to/your/project --dry-run    # show what would happen
#   ./install.sh /path/to/your/project --python 3.13  # pin the Python version
#   ./install.sh /path/to/your/project --check      # report version drift, change nothing
#   ./install.sh --version                          # print the pack version
#
# Safe to re-run. Existing settings.json is backed up before it is changed.
# See docs/CHANGE_CONTROL.md for the upgrade and rollback procedure.

set -euo pipefail

PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$PACK_DIR/VERSION" ]; then
  PACK_VERSION="$(tr -d '[:space:]' < "$PACK_DIR/VERSION")"
else
  PACK_VERSION="unknown"
fi

# Files the installer overwrites on an upgrade. --check diffs exactly these.
TRACKED_FILES="AGENTS.md pyproject.toml uv.toml uv.lock sensitive-patterns.json"
TRACKED_DIRS="hooks scripts tests"

TARGET=""
WITH_EXTRAS=0
DRY_RUN=0
CHECK_ONLY=0
PYTHON_PIN=""
EXPECT_PYTHON=0

for arg in "$@"; do
  if [ "$EXPECT_PYTHON" = 1 ]; then
    PYTHON_PIN="$arg"
    EXPECT_PYTHON=0
    continue
  fi
  case "$arg" in
    --extras)  WITH_EXTRAS=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --check)   CHECK_ONLY=1 ;;
    --python)  EXPECT_PYTHON=1 ;;
    --python=*) PYTHON_PIN="${arg#--python=}" ;;
    --version|-V)
      echo "Memory Palace $PACK_VERSION"
      exit 0 ;;
    -h|--help)
      sed -n '3,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    -*)
      echo "ERROR: unknown flag: $arg" >&2; exit 2 ;;
    *)
      if [ -n "$TARGET" ]; then echo "ERROR: more than one target given" >&2; exit 2; fi
      TARGET="$arg" ;;
  esac
done

if [ "$EXPECT_PYTHON" = 1 ]; then
  echo "ERROR: --python needs a version, e.g. --python 3.13" >&2
  exit 2
fi

if [ -z "$TARGET" ]; then
  echo "ERROR: no target project given." >&2
  echo "Usage: ./install.sh /path/to/your/project [--extras] [--dry-run] [--check]" >&2
  echo "       ./install.sh --version" >&2
  exit 2
fi

say()  { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
run()  { if [ "$DRY_RUN" = 1 ]; then say "[dry-run] $*"; else eval "$@"; fi }

# ── --check: report drift, change nothing ──────────────────────────────
if [ "$CHECK_ONLY" = 1 ]; then
  if [ ! -d "$TARGET" ]; then
    echo "ERROR: target directory does not exist: $TARGET" >&2
    exit 1
  fi
  TARGET="$(cd "$TARGET" && pwd)"

  step "Memory Palace drift check"
  say "pack version:    $PACK_VERSION  ($PACK_DIR)"

  if [ ! -d "$TARGET/mem-palace" ]; then
    say "installed:       NOT INSTALLED  ($TARGET)"
    printf '\nMemory Palace is not installed here. Install it:\n  ./install.sh "%s" --extras\n' "$TARGET"
    exit 1
  fi

  if [ -f "$TARGET/mem-palace/INSTALLED_VERSION" ]; then
    INSTALLED_VERSION="$(tr -d '[:space:]' < "$TARGET/mem-palace/INSTALLED_VERSION")"
  else
    INSTALLED_VERSION="unknown (pre-1.0.0, or installed by hand)"
  fi
  say "installed:       $INSTALLED_VERSION  ($TARGET/mem-palace)"

  step "Comparing tracked files"
  DRIFTED=0
  for item in $TRACKED_FILES; do
    if [ ! -f "$TARGET/mem-palace/$item" ]; then
      say "MISSING   $item"
      DRIFTED=$((DRIFTED + 1))
    elif ! diff -q "$PACK_DIR/mem-palace/$item" "$TARGET/mem-palace/$item" >/dev/null 2>&1; then
      say "DIFFERS   $item"
      DRIFTED=$((DRIFTED + 1))
    fi
  done
  for item in $TRACKED_DIRS; do
    if [ ! -d "$TARGET/mem-palace/$item" ]; then
      say "MISSING   $item/"
      DRIFTED=$((DRIFTED + 1))
      continue
    fi
    while IFS= read -r rel; do
      [ -z "$rel" ] && continue
      if [ ! -f "$TARGET/mem-palace/$item/$rel" ]; then
        say "MISSING   $item/$rel"
        DRIFTED=$((DRIFTED + 1))
      elif ! diff -q "$PACK_DIR/mem-palace/$item/$rel" "$TARGET/mem-palace/$item/$rel" >/dev/null 2>&1; then
        say "DIFFERS   $item/$rel"
        DRIFTED=$((DRIFTED + 1))
      fi
    done <<EOF
$(cd "$PACK_DIR/mem-palace/$item" && find . -name '*.py' -o -name '*.md' -o -name '*.sh' | sed 's|^\./||' | sort)
EOF
  done

  if [ "$DRIFTED" = 0 ]; then
    say "no drift — every tracked file matches the pack"
  fi

  step "Memory store"
  for d in docs/daily docs/knowledge; do
    if [ -d "$TARGET/$d" ]; then
      COUNT="$(find "$TARGET/$d" -name '*.md' -type f 2>/dev/null | grep -c . || true)"
      say "$d/  $COUNT markdown file(s)  — never touched by an upgrade"
    else
      say "$d/  MISSING"
    fi
  done

  printf '\n'
  if [ "$DRIFTED" = 0 ] && [ "$INSTALLED_VERSION" = "$PACK_VERSION" ]; then
    echo "Up to date. Nothing to do."
    exit 0
  fi
  echo "To upgrade (overwrites the code, never the memory store):"
  echo "  ./install.sh \"$TARGET\" --extras"
  echo ""
  echo "Read CHANGELOG.md first if this is a MAJOR version change."
  echo "A DIFFERS line on a file you customised means the upgrade will revert it."
  echo "See docs/CHANGE_CONTROL.md, section 4."
  exit 0
fi

# ── 1. Preflight ───────────────────────────────────────────────────────
step "Preflight"

if [ ! -d "$TARGET" ]; then
  echo "ERROR: target directory does not exist: $TARGET" >&2
  exit 1
fi
TARGET="$(cd "$TARGET" && pwd)"
say "pack version:   $PACK_VERSION"
say "target project: $TARGET"

if [ "$TARGET" = "$PACK_DIR" ]; then
  echo "ERROR: target is the pack itself. Pick your project directory." >&2
  exit 1
fi

MISSING=0
for tool in uv python3 git; do
  if command -v "$tool" >/dev/null 2>&1; then
    say "found $tool: $(command -v "$tool")"
  else
    say "MISSING $tool"
    MISSING=1
  fi
done
if [ "$MISSING" = 1 ]; then
  echo "" >&2
  echo "ERROR: install the missing tools first." >&2
  echo "  uv:      https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [ -d "$TARGET/mem-palace" ]; then
  say "note: $TARGET/mem-palace already exists — files will be overwritten"
fi

# ── 2. Copy the kit ────────────────────────────────────────────────────
step "Copying the memory kit"

run "mkdir -p \"$TARGET/mem-palace\""
for item in AGENTS.md pyproject.toml uv.toml uv.lock sensitive-patterns.json .gitignore hooks scripts tests; do
  run "cp -R \"$PACK_DIR/mem-palace/$item\" \"$TARGET/mem-palace/\""
  say "copied mem-palace/$item"
done

run "printf '%s\\n' \"$PACK_VERSION\" > \"$TARGET/mem-palace/INSTALLED_VERSION\""
say "stamped INSTALLED_VERSION = $PACK_VERSION"

# ── 3. Create the memory store ─────────────────────────────────────────
step "Creating the memory store"

for d in docs/daily docs/knowledge/concepts docs/knowledge/connections docs/knowledge/qa docs/knowledge/dreams docs/knowledge/lesson-learned; do
  run "mkdir -p \"$TARGET/$d\""
  say "ensured $d/"
done

if [ ! -f "$TARGET/docs/knowledge/index.md" ]; then
  if [ "$DRY_RUN" = 1 ]; then
    say "[dry-run] would create docs/knowledge/index.md"
  else
    cat > "$TARGET/docs/knowledge/index.md" <<'IDX'
# Knowledge Base Index

| Article | Summary | Compiled From | Updated |
|---------|---------|---------------|---------|
IDX
    say "created docs/knowledge/index.md"
  fi
else
  say "docs/knowledge/index.md already exists — left alone"
fi

if [ ! -f "$TARGET/docs/knowledge/log.md" ]; then
  run "printf '# Build Log\\n\\n' > \"$TARGET/docs/knowledge/log.md\""
  say "created docs/knowledge/log.md"
else
  say "docs/knowledge/log.md already exists — left alone"
fi

# ── 4. Optional context-hygiene hooks ──────────────────────────────────
if [ "$WITH_EXTRAS" = 1 ]; then
  step "Installing context-hygiene hooks"
  run "mkdir -p \"$TARGET/.claude/hooks\""
  for f in session-size-warn.py drift-check.py prefer-native-search.py doc-heal.sh; do
    run "cp \"$PACK_DIR/extras/hooks/$f\" \"$TARGET/.claude/hooks/$f\""
    run "chmod +x \"$TARGET/.claude/hooks/$f\""
    say "installed .claude/hooks/$f"
  done
fi

# ── 5. Merge hook config into .claude/settings.json ────────────────────
step "Wiring hooks into .claude/settings.json"

run "mkdir -p \"$TARGET/.claude\""
SETTINGS="$TARGET/.claude/settings.json"

if [ -f "$SETTINGS" ]; then
  BACKUP="$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"
  run "cp \"$SETTINGS\" \"$BACKUP\""
  say "backed up existing settings to $(basename "$BACKUP")"
fi

TEMPLATES="$PACK_DIR/templates/settings.core.json"
if [ "$WITH_EXTRAS" = 1 ]; then
  TEMPLATES="$TEMPLATES $PACK_DIR/templates/settings.extras.json"
fi

if [ "$DRY_RUN" = 1 ]; then
  say "[dry-run] would merge these hook templates into .claude/settings.json:"
  for t in $TEMPLATES; do say "[dry-run]   $(basename "$t")"; done
else
  MEM_PALACE_SETTINGS="$SETTINGS" MEM_PALACE_TEMPLATES="$TEMPLATES" python3 <<'PY'
import json, os, pathlib

settings_path = pathlib.Path(os.environ["MEM_PALACE_SETTINGS"])
templates = os.environ["MEM_PALACE_TEMPLATES"].split()

if settings_path.exists() and settings_path.read_text(encoding="utf-8").strip():
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
else:
    settings = {}

settings.setdefault("hooks", {})
added = 0

for template_path in templates:
    template = json.loads(pathlib.Path(template_path).read_text(encoding="utf-8"))
    for event, groups in template["hooks"].items():
        existing_groups = settings["hooks"].setdefault(event, [])
        for group in groups:
            matcher = group.get("matcher", "")
            target = next(
                (g for g in existing_groups if g.get("matcher", "") == matcher),
                None,
            )
            if target is None:
                existing_groups.append(json.loads(json.dumps(group)))
                added += len(group.get("hooks", []))
                continue
            target.setdefault("hooks", [])
            known = {json.dumps(h.get("command", ""), sort_keys=True) for h in target["hooks"]}
            for hook in group.get("hooks", []):
                key = json.dumps(hook.get("command", ""), sort_keys=True)
                if key in known:
                    continue
                target["hooks"].append(json.loads(json.dumps(hook)))
                added += 1

settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
print(f"  merged hook config: {added} hook command(s) added")
PY
fi

# ── 6. Install dependencies ────────────────────────────────────────────
step "Installing Python dependencies"

SYNC_ARGS=""
if [ -n "$PYTHON_PIN" ]; then
  SYNC_ARGS="--python $PYTHON_PIN"
fi

if [ "$DRY_RUN" = 1 ]; then
  say "[dry-run] would run: uv sync $SYNC_ARGS  (in $TARGET/mem-palace)"
else
  SYNC_OK=0
  ( cd "$TARGET/mem-palace" && uv sync $SYNC_ARGS ) || SYNC_OK=$?
  if [ "$SYNC_OK" != 0 ]; then
    echo "" >&2
    echo "ERROR: uv sync failed (exit $SYNC_OK)." >&2
    echo "" >&2
    echo "Most common cause: uv picked a Python built for the wrong CPU" >&2
    echo "architecture, so a dependency had to compile from source." >&2
    echo "Pin a working interpreter and re-run:" >&2
    echo "" >&2
    echo "  uv python list                                  # see what is available" >&2
    echo "  ./install.sh \"$TARGET\" --python 3.13            # then pin one" >&2
    exit 1
  fi
  say "uv sync complete"
fi

# ── 7. Verify ──────────────────────────────────────────────────────────
step "Verifying"

if [ "$DRY_RUN" = 1 ]; then
  say "[dry-run] would run the SessionStart hook and the sensitive-data tests"
else
  if ( cd "$TARGET/mem-palace" && uv run python hooks/session-start.py >/dev/null ); then
    say "PASS  SessionStart hook produced valid output"
  else
    say "FAIL  SessionStart hook errored — see the output above"
    exit 1
  fi

  if ( cd "$TARGET/mem-palace" && uv run python -m unittest discover -s tests -q >/dev/null 2>&1 ); then
    say "PASS  sensitive-data scanner tests"
  else
    say "FAIL  sensitive-data scanner tests"
    exit 1
  fi

  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SETTINGS"; then
    say "PASS  .claude/settings.json is valid JSON"
  else
    say "FAIL  .claude/settings.json is not valid JSON"
    exit 1
  fi
fi

# ── Done ───────────────────────────────────────────────────────────────
cat <<DONE

==> Done.

Next steps:
  1. Add the memory store to your repo, or ignore it:
       git add docs/daily docs/knowledge      # keep the memory in git
       echo 'docs/daily/' >> .gitignore       # or keep it local only
  2. Start a Claude Code session in $TARGET.
     The SessionStart hook injects the knowledge base index.
  3. End the session. Check the daily log:
       cat $TARGET/docs/daily/\$(date +%F).md
  4. Read the hook log if nothing appears:
       tail $TARGET/mem-palace/scripts/flush.log

Optional:
  export MEM_COMP_DREAM_ENABLED=1              # enable repeated-correction lessons
  export MEM_PALACE_SLACK_CHANNEL=C0123456789  # enable the daily Slack summary
DONE
