#!/usr/bin/env python3
# PreToolUse(Bash) hook: when shell grep/find/rg is used for code search, nudge
# toward the native Grep/Glob tools (+ a code-graph MCP for structure). Rate-limited
# to once per session so it informs without nagging. Never blocks — always exit 0.
import sys, json, os, tempfile, re

SEARCH = re.compile(r"^(?:\S+=\S+\s+)*(?:sudo\s+)?(?:grep|egrep|fgrep|rg|find)\b")

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Bash":
        return
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not isinstance(cmd, str) or not SEARCH.match(cmd.lstrip()):
        return
    # once per session
    sid = data.get("session_id") or "nosession"
    marker = os.path.join(tempfile.gettempdir(), "mempalace-search-nudge-" + re.sub(r"\W", "", sid))
    if os.path.exists(marker):
        return
    try:
        open(marker, "w").close()
    except Exception:
        pass
    ctx = (
        "[search] Prefer the Grep/Glob tools over shell grep/find/rg — they're faster, "
        "structured, and skip a shell round-trip. For code STRUCTURE (callers, "
        "definitions, dependents, blast-radius) prefer a code-graph MCP server "
        "if one is configured, not a text search. "
        "(Shown once per session.)"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": ctx,
        }
    }))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # ponytail: fail-silent, never block a tool call
