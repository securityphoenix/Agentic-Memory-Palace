#!/bin/bash
# Stop hook — self-healing documentation reminder.
#
# Fires when a session stops. If source files changed in the working tree but no
# markdown changed with them, print a reminder. Stdout is injected into Claude's
# context, so the agent sees it and can offer to update the docs.
#
# Never blocks: always exits 0.
#
# Config (optional environment variables):
#   DOC_HEAL_DOC_DIR    directory treated as documentation. Default: docs
#   DOC_HEAL_MAX_FILES  how many changed files to list. Default: 15

set -u

cat >/dev/null 2>&1 || true   # drain the hook JSON on stdin; we do not need it

DOC_DIR="${DOC_HEAL_DOC_DIR:-docs}"
MAX_FILES="${DOC_HEAL_MAX_FILES:-15}"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

changed() {
  { git diff --name-only HEAD 2>/dev/null; git diff --cached --name-only 2>/dev/null; } | sort -u | grep -v '^$'
}

ALL="$(changed || true)"
[ -z "$ALL" ] && exit 0

CODE="$(printf '%s\n' "$ALL" | grep -vE '\.(md|mdc|markdown)$' | grep -vE "^${DOC_DIR}/" || true)"
DOCS="$(printf '%s\n' "$ALL" | grep -E '\.(md|mdc|markdown)$' || true)"

# No code changed, or docs were updated alongside the code — nothing to say.
[ -z "$CODE" ] && exit 0
[ -n "$DOCS" ] && exit 0

echo "## Documentation Self-Healing Check"
echo ""
echo "Source files changed in this session, but no markdown changed with them."
echo "Decide whether the documentation needs an update before this work lands."
echo ""
echo "### Changed source files"
echo ""
printf '%s\n' "$CODE" | head -n "$MAX_FILES" | while read -r f; do
  [ -n "$f" ] && echo "  - $f"
done
TOTAL="$(printf '%s\n' "$CODE" | grep -c . || true)"
if [ "$TOTAL" -gt "$MAX_FILES" ]; then
  echo "  - ...and $((TOTAL - MAX_FILES)) more"
fi
echo ""
echo "If these changes need no doc update, ignore this reminder."

exit 0
