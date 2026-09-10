#!/usr/bin/env python3
# UserPromptSubmit hook: warn when the session transcript grows large, nudging
# toward /clear between unrelated tasks. Warns ONCE per size tier crossed (2/5/10 MB)
# so a long session gets escalating reminders, not one per prompt. Fail-silent.
import sys, json, os, tempfile, re

TIERS_MB = [2, 5, 10, 20]  # thresholds; index+1 == tier number

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    tpath = data.get("transcript_path")
    if not tpath or not os.path.exists(tpath):
        return
    size_mb = os.path.getsize(tpath) / (1024 * 1024)
    tier = sum(1 for t in TIERS_MB if size_mb >= t)  # 0..len(TIERS_MB)
    if tier == 0:
        return
    sid = data.get("session_id") or "nosession"
    marker = os.path.join(tempfile.gettempdir(), "mempalace-size-warn-" + re.sub(r"\W", "", sid))
    prev = 0
    try:
        prev = int(open(marker).read().strip() or "0")
    except Exception:
        prev = 0
    if tier <= prev:
        return  # already warned at this tier or higher
    try:
        open(marker, "w").write(str(tier))
    except Exception:
        pass
    ctx = (
        f"[session-size] This session's transcript is ~{size_mb:.0f}MB — it's getting long. "
        "Long sessions bloat context and mix unrelated task history, which degrades reasoning. "
        "If the current task is done or you're switching topics, run /clear to start fresh "
        "(one task ≈ one session). Ignore if you're mid-task."
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
        pass  # ponytail: fail-silent, never block a prompt
