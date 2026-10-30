#!/usr/bin/env python3
"""
PT Gary — Log a completed set (v1)

Usage:
  python3 scripts/log_set.py <weight_kg> <reps> [--note "..."]
  python3 scripts/log_set.py --skip          # mark current exercise skipped, advance
  python3 scripts/log_set.py --status        # print current position, change nothing

Appends the set to scripts/.session_state.json AND mirrors it into the session log
JSON, advances the position when the target set count is met, then commits+pushes so
the dashboard live view updates.

Prints a machine-readable line for the agent:
  SET_LOGGED|<exercise>|set <n>/<target>|45kg x 12|ex <i>/<N>|<next or COMPLETE>
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/gary/Projects/gary-pt")
STATE = REPO / "scripts" / ".session_state.json"


def load():
    if not STATE.exists():
        sys.exit("No active session (no .session_state.json).")
    return json.loads(STATE.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("weight", nargs="?", type=float)
    ap.add_argument("reps", nargs="?", type=int)
    ap.add_argument("--skip", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    state = load()
    exs = state["exercises"]
    i = state.get("current_exercise", 0)

    if a.status:
        if i >= len(exs):
            print("SESSION_COMPLETE")
            return 0
        e = exs[i]
        print(f"AT|ex {i+1}/{len(exs)}|{e['name']}|set {state.get('current_set',1)}/{e['target_sets']}"
              f"|{e.get('target_weight_kg')}kg x {e['target_reps']}")
        for j, x in enumerate(exs):
            mark = "->" if j == i else ("done" if x.get("sets") or x.get("skipped") else "   ")
            print(f"   {mark} {j+1}. {x['name']} {x.get('sets') or ''}")
        return 0

    if i >= len(exs):
        print("SESSION_COMPLETE")
        return 0

    e = exs[i]
    if a.skip:
        e["skipped"] = True
        e["sets"] = []
        state["current_exercise"] = i + 1
        state["current_set"] = 1
        msg = f"SKIPPED|{e['name']}|ex {state['current_exercise']}/{len(exs)}"
    else:
        if a.weight is None or a.reps is None:
            sys.exit("Need <weight_kg> <reps> (or --skip / --status).")
        s = {"set": len(e["sets"]) + 1, "weight_kg": a.weight, "reps": a.reps}
        if a.note:
            s["notes"] = a.note
        e["sets"].append(s)
        state["current_set"] = state.get("current_set", 1) + 1
        done = len(e["sets"]) >= e["target_sets"]
        if done:
            state["current_exercise"] = i + 1
            state["current_set"] = 1
        msg = (f"SET_LOGGED|{e['name']}|set {len(e['sets'])}/{e['target_sets']}"
               f"|{a.weight}kg x {a.reps}|ex {state['current_exercise']}/{len(exs)}")

    # Persist state
    STATE.write_text(json.dumps(state, indent=2))

    # Navigate the log file for this session
    log_path = REPO / "logs" / f"{state.get('date', '')}-{state['session_type']}.json"
    if not log_path.exists():
        cands = sorted((REPO / "logs").glob(f"*-{state['session_type']}.json"), reverse=True)
        log_path = cands[0] if cands else None
    if log_path and log_path.exists():
        log = json.loads(log_path.read_text())
        log["exercises"] = exs
        # keep top-level flags the state carries forward
        for k in ("modified_session", "modification", "progression_skipped", "ad_hoc", "notes"):
            if k in state and k not in log:
                log[k] = state[k]
        log_path.write_text(json.dumps(log, indent=2))

    nxt = exs[state["current_exercise"]]["name"] if state["current_exercise"] < len(exs) else "COMPLETE"
    msg += f"|{nxt}"
    print(msg)

    def git(*c):
        return subprocess.run(["git", *c], cwd=str(REPO), capture_output=True, text=True).returncode == 0

    git("add", "-A")
    git("commit", "-m", f"{e['name']}: {msg}")
    git("push", "origin", "main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
