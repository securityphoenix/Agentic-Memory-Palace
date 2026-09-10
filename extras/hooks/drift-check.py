#!/usr/bin/env python3
# UserPromptSubmit hook: detect topic drift. Accumulates the session's significant
# vocabulary (identifiers, file paths, content words) and flags a new prompt whose
# overlap with that history is near-zero — i.e. you've switched to an unrelated task
# and would be better off in a fresh session. Heuristic, conservative, rate-limited.
# Fail-silent — never blocks a prompt.
import sys, json, os, tempfile, re

STOP = set((
    "the a an and or but if then else for while with without this that these those from "
    "into onto over under about above below can could should would will shall may might "
    "must have has had been being does did doing your you yours it its are was were "
    "not yes please help need want make made check give given also here there what when "
    "where which who whom whose how out off than them they their some any all each both "
    "more most other via use used using can't cant just like get got now new add added "
    "fix fixed run running proceed review verify update updated change changed"
).split())

# require the session to have real history AND the new prompt to be substantive
MIN_PROMPTS = 3        # session must have this many prior prompts
MIN_ACC_TOKENS = 12    # accumulated vocab must be this rich
MIN_NEW_TOKENS = 4     # new prompt must carry this many significant tokens
OVERLAP_FLOOR = 0.12   # below this fraction of shared tokens => probable drift
COOLDOWN = 2           # don't warn again within N prompts

def toks(s):
    words = re.findall(r"[a-z][a-z0-9_/.\-]{3,}", s.lower())
    return {w for w in words if w not in STOP}

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or len(prompt) > 6000:
        return
    if re.search(r"/clear\b|new session|switch(ing)? (task|topic|context)", prompt, re.I):
        return  # user already signalled the switch

    sid = data.get("session_id") or "nosession"
    path = os.path.join(tempfile.gettempdir(), "mempalace-drift-" + re.sub(r"\W", "", sid) + ".json")
    st = {"count": 0, "tokens": [], "last_warn": -99}
    try:
        st = json.load(open(path))
    except Exception:
        pass

    new = toks(prompt)
    acc = set(st.get("tokens", []))
    count = st.get("count", 0)
    overlap = (len(new & acc) / len(new)) if new else 1.0

    drift = (
        count >= MIN_PROMPTS
        and len(acc) >= MIN_ACC_TOKENS
        and len(new) >= MIN_NEW_TOKENS
        and overlap < OVERLAP_FLOOR
        and (count - st.get("last_warn", -99)) >= COOLDOWN
    )

    st["count"] = count + 1
    st["tokens"] = list(acc | new)[:400]  # cap to bound the state file
    if drift:
        st["last_warn"] = count
    try:
        json.dump(st, open(path, "w"))
    except Exception:
        pass

    if not drift:
        return
    ctx = (
        "[drift] This prompt shares almost no topic overlap with what this session has "
        "covered so far — it looks like a new, unrelated task. Consider /clear to start a "
        "fresh session: focused context reasons better and costs less. Ignore if this is "
        "a genuine follow-up on the same work."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": ctx,
        }
    }))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
