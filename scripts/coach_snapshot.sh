#!/usr/bin/env bash
#
# coach_snapshot.sh — THE single boot-time state probe for a PT coaching session.
#
# WHY THIS EXISTS: The PT coaching loop previously re-ran 6 separate probing
# commands on EVERY turn (session_start.py --dry-run, git log, git status,
# .session_state.json, ls programs/, ls docs/) — up to ~90 copies each, 646
# terminal calls in one session (2026-09-20). This script collapses the whole
# probe into ONE call that emits one snapshot block. Run it once at session
# start, hold the output in context, and re-issue ONLY the specific file you
# just mutated. Never re-run this to "see the state again" — that is the loop.
#
# USAGE:
#   coach_snapshot.sh [REPO_PATH]      # default: /Users/gary/Projects/gary-pt
#
#   coach_snapshot.sh /Users/gary/Projects/amy-pt
#
# EXIT CODE: 0 always (informational). Read the [SESSION-GUARD] section for
# whether a session is active.
#
set -uo pipefail

REPO="${1:-/Users/gary/Projects/gary-pt}"
cd "$REPO" 2>/dev/null || { echo "ERROR: repo not found: $REPO" >&2; exit 1; }

STATE="scripts/.session_state.json"
INDEX="logs/index.json"

echo "================ SNAPSHOT: $(basename "$REPO") — $(TZ='Australia/Adelaide' date '+%a %-d %b %H:%M') ================"

echo ""
echo "----- [SESSION-GUARD] active-session check -----"
if [ -f "scripts/session_start.py" ]; then
  # gary-pt fast-path guard (Josh)
  python3 scripts/session_start.py --dry-run 2>&1
else
  # amy-pt: no fast-path script — infer guard from state file
  if [ -f "$STATE" ]; then
    status=$(python3 -c "import json;print(json.load(open('$STATE')).get('status','?'))" 2>/dev/null)
    sess=$(python3 -c "import json;d=json.load(open('$STATE'));print(d.get('session_name') or d.get('session_type') or '')" 2>/dev/null)
    if [ "$status" = "idle" ] || [ "$status" = "?" ]; then
      echo "No active session (state status: ${status:-missing})."
    elif [ -n "$sess" ]; then
      echo "Another session is active: $sess. Finish it first — say \"finish\" to end it, then start again."
    fi
  fi
fi

echo ""
echo "----- [STATE] $STATE -----"
if [ -f "$STATE" ]; then
  cat "$STATE"
else
  echo "(no state file — no active session)"
fi

echo ""
echo "----- [INDEX] $INDEX (index[0] carries active/in_progress marker) -----"
if [ -f "$INDEX" ]; then
  python3 -c "import json,sys; d=json.load(open('$INDEX')); print(json.dumps(d[0] if isinstance(d,list) and d else d, indent=2, default=str))" 2>/dev/null || head -60 "$INDEX"
else
  echo "(no index file)"
fi

echo ""
echo "----- [PROGRAM-FILES] programs/ (find status: active) -----"
ls programs/ 2>/dev/null | head -20
echo "--- active marker ---"
grep -l 'status: active' programs/*.md 2>/dev/null || echo "(none with 'status: active')"

echo ""
echo "----- [GIT STATUS] -----"
git status -sb 2>&1

echo ""
echo "----- [GIT LOG] last 5 -----"
git log --oneline -5 2>&1

echo ""
echo "===== END SNAPSHOT ====="