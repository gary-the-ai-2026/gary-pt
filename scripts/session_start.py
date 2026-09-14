#!/usr/bin/env python3
"""
PT Gary — Session Start Shortcut (v1)
Squashes the full 11-step session-start checklist into one invocation.

Reads the active program, determines the next session in rotation, builds the
exercise list, calibrates weights from the last same-type session, writes the
log JSON + .session_state.json, stamps start time, rebuilds index.json, and
commits+pushes. Prints a ready-to-present table for the agent.

Usage:
  python3 session_start.py                # auto-detect next session & full flow
  python3 session_start.py --dry-run      # show what WOULD happen, change nothing
  python3 session_start.py --type lower-b # force a specific session type

Exit 0 on success. The script NEVER prompts; all decisions are deterministic.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ADL = "Australia/Adelaide"
REPO = Path("/Users/gary/Projects/gary-pt")
PROGRAMS = REPO / "programs"
LOGS = REPO / "logs"
STATE = REPO / "scripts" / ".session_state.json"
INDEX = LOGS / "index.json"

# The rotation for the CURRENT active program (Cycle 3 4-day UL). If the active
# program changes split, update this to match its config.
ROTATION = ["upper-a", "lower-a", "upper-b", "lower-b"]

# Exercise-name → session-type-keyword used when calibrating from prior logs.
# For a 4-day split the previous "same-type" is not a 1:1 name; we calibrate a
# compound from the most recent session that trained that muscle group. If we
# can't find a match we fall back to the program target (already calibrated in
# the Loading Notes).


def adl_now():
    """Return local Adelaide time as (YYYY-MM-DD, HH:MM)."""
    import zoneinfo
    tz = zoneinfo.ZoneInfo(ADL)
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M")


def find_active_program():
    """Return the cycle-*.md with `status: active` (and its parsed YAML).

    If more than one file is marked active (stale duplicate), pick the HIGHEST
    cycle number — that's the current program.
    """
    candidates = []
    for f in sorted(PROGRAMS.glob("cycle-*.md")):
        txt = f.read_text()
        m = re.search(r"^status:\s*(\S+)", txt, re.M)
        cycm = re.search(r"^cycle:\s*(\d+)", txt, re.M)
        if m and m.group(1) == "active":
            cycle = int(cycm.group(1)) if cycm else 0
            yaml = dict(re.findall(r"^(\w[\w_]*):\s*(.+)$", txt, re.M))
            candidates.append((cycle, f, txt, yaml))
    if not candidates:
        raise SystemExit("No active program found. Check programs/cycle-*.md.")
    candidates.sort(key=lambda c: c[0], reverse=True)
    _, f, txt, yaml = candidates[0]
    return f, txt, yaml


def last_completed_type():
    """Return the type of the most recent completed session (or None)."""
    if not INDEX.exists():
        return None
    for e in json.loads(INDEX.read_text()):
        if e.get("status") == "complete":
            return e.get("type")
    return None


def determine_next_session(program_yaml):
    """Cross-check program next_session against rotation & last completed."""
    next_s = program_yaml.get("next_session", "").strip()
    last = last_completed_type()

    # If an in-progress session exists, that's the current one — not a new start.
    if STATE.exists():
        try:
            sd = json.loads(STATE.read_text())
            if sd.get("session_type"):
                return sd["session_type"], sd.get("session_name", "")
        except Exception:
            pass

    # Rotation sanity: if last completed is the same as next_session, next_session
    # is stale (bug from old flow) — advance rotation.
    if last in ROTATION and next_s in ROTATION:
        if last == next_s:
            idx = ROTATION.index(next_s)
            next_s = ROTATION[(idx + 1) % len(ROTATION)]
    elif last not in ROTATION and next_s not in ROTATION:
        # Old 3-day names encountered: fall back to a sensible default start
        next_s = ROTATION[0]
    return next_s, next_s.upper()


def parse_program_section(program_txt, section_key):
    """Return list of exercise rows [num, name, sets, weight, reps] for a section."""
    headers = {"upper-a": "## Upper A", "lower-a": "## Lower A",
               "upper-b": "## Upper B", "lower-b": "## Lower B"}
    header = headers.get(section_key)
    if not header or header not in program_txt:
        raise SystemExit(f"Section {header} not found in active program.")

    after = program_txt.split(header, 1)[1]
    # Stop at the next '## ' heading
    nxt = re.search(r"\n## ", after)
    if nxt:
        after = after[:nxt.start()]
    # parse table rows '| 1 | Name | 3 | 65.0kg | 8–10 | 2–3 min |'
    rows = []
    for line in after.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        if not cells[0].isdigit():
            continue
        num = int(cells[0])
        name = cells[1]
        sets = int(cells[2]) if cells[2].isdigit() else 3
        weight_raw = cells[3]
        reps = cells[4]
        # weight like '65.0kg' or '12.0kg/side' or 'BW'
        wm = re.search(r"([\d.]+)", weight_raw)
        weight = float(wm.group(1)) if wm else None
        rows.append({"num": num, "name": name, "target_sets": sets,
                     "target_reps": reps, "target_weight_kg": weight,
                     "skipped": False, "sets": []})
    if not rows:
        raise SystemExit(f"No table rows parsed for {header}.")
    return rows


LOWER_BODY = {"squat", "deadlift", "rdl", "romanian", "leg press", "leg extension",
              "leg curl", "bulgarian", "split squat", "lunge", "calf raise",
              "hip thrust", "glute bridge", "reverse lunge"}


def _is_lower(name: str) -> bool:
    n = name.lower()
    return any(sb in n for sb in LOWER_BODY)


def _parse_rep_range(reps_str: str):
    """Return (low, high) from a rep-range string like '8–10' or '12'."""
    r = str(reps_str or "").replace("\u2013", "-").replace("\u2014", "-").strip()
    if "-" in r:
        a, b = r.split("-", 1)
        lo = int(a.strip()) if a.strip().isdigit() else 8
        hi = int(b.strip()) if b.strip().isdigit() else lo
        return lo, hi
    v = int(r) if r and r.isdigit() else 8
    return v, v


def calibrate_with_progression(e_list, section_key):
    """Calibrate each exercise from the most recent same-type completed session.

    Non-NEGOTIABLE per skill (progression rules):
      - Start with the HIGHEST weight from the last same-type session's sets.
      - All sets at top of rep range  -> +2.5kg (upper) / +5kg (lower)
      - Some at top, some in range    -> repeat weight
      - 2+ sets below bottom of range -> -5%
    Session-derived actuals win over program targets. If no prior same-type
    session exists, keep the program targets (already calibrated in Loading
    Notes during cycle generation).
    """
    pat = f"*-{section_key}.json"
    ms = sorted(LOGS.glob(pat), reverse=True)
    prior = None
    for f in ms:
        try:
            d = json.loads(f.read_text())
            if d.get("status") == "complete" and d.get("exercises"):
                prior = d
                break
        except Exception:
            continue
    if not prior:
        return e_list  # no prior same-type; keep program targets

    pmap = {ex["name"]: ex for ex in prior["exercises"]}
    for ex in e_list:
        p = pmap.get(ex["name"])
        if not p or not p.get("sets"):
            continue
        sets = [s for s in p["sets"] if s.get("reps") is not None and s.get("weight_kg")]
        if not sets:
            continue
        weights = [s.get("weight_kg") for s in sets if s.get("weight_kg")]
        base = float(max(weights)) if weights else None
        if base is None:
            continue
        lo, hi = _parse_rep_range(ex.get("target_reps"))
        reps = [int(s.get("reps", 0)) for s in sets]
        n_top = sum(1 for r in reps if r >= hi)
        n_below = sum(1 for r in reps if r < lo)
        n_total = len(reps)

        if n_top == n_total:
            # All sets at top -> bump (skip bump for bodyweight movements)
            bump = 5.0 if _is_lower(ex["name"]) else 2.5
            ex["target_weight_kg"] = round(base + bump, 1)
        elif n_below >= 2:
            # 2+ sets below bottom -> -5%
            ex["target_weight_kg"] = round(base * 0.95, 1)
        else:
            # Some at top / some in range -> repeat
            ex["target_weight_kg"] = base
    return e_list


def run_git(cmd):
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--type", choices=ROTATION, default=None)
    args = ap.parse_args()

    today, now_hm = adl_now()
    prog_file, prog_txt, prog_yaml = find_active_program()
    cycle = int(prog_yaml.get("cycle", "3"))
    week = int(prog_yaml.get("week", "1"))

    session_type, session_name = determine_next_session(prog_yaml)
    if args.type:
        session_type = args.type
        session_name = session_type.upper()

    # In-progress guard: refuse to clobber a live session.
    if STATE.exists():
        try:
            sd = json.loads(STATE.read_text())
            if sd.get("session_type") and sd.get("session_type") != session_type:
                raise SystemExit(f"Session {sd['session_type']} already active. End it before starting {session_type}.")
        except SystemExit:
            raise
        except Exception:
            pass

    exercises = parse_program_section(prog_txt, session_type)
    exercises = calibrate_with_progression(exercises, session_type)

    log_path = LOGS / f"{today}-{session_type}.json"

    if args.dry_run:
        print(f"[dry-run] next session: {session_type} ({session_name})")
        print(f"[dry-run] program: {prog_file.name} | cycle {cycle} week {week}")
        print(f"[dry-run] would write: {log_path.name} + {STATE}")
        for e in exercises:
            w = f"{e['target_weight_kg']}kg" if e['target_weight_kg'] else "BW"
            print(f"  {e['num']:>2}. {e['name']:<40} {e['target_sets']} × {e['target_reps']:<6} @ {w}")
        print(f"[dry-run] would rebuild index.json + git commit+push")
        return 0

    # Write session log
    log = {
        "session_id": f"{today}-{session_type}",
        "date": today,
        "type": session_type,
        "status": "in_progress",
        "started": now_hm,
        "cycle": cycle,
        "week": week,
        "exercises": exercises,
        "notes": "",
    }
    log_path.write_text(json.dumps(log, indent=2))

    # Write session_state (linear mode, Josh)
    state = {
        "session_type": session_type,
        "session_name": session_name,
        "current_exercise": 0,
        "current_set": 1,
        "exercises": exercises,
        "log": {},
    }
    STATE.write_text(json.dumps(state, indent=2))

    # Rebuild index.json (prepend in-progress entry, newest first)
    if INDEX.exists():
        index = json.loads(INDEX.read_text())
    else:
        index = []
    index = [e for e in index if e.get("name") != log_path.name]
    index.insert(0, {
        "name": log_path.name,
        "date": today,
        "type": session_type,
        "status": "in_progress",
        "cycle": cycle,
        "ad_hoc": False,
        "resumed_from": None,
        "exercise_count": len(exercises),
        "skipped_count": 0,
    })
    INDEX.write_text(json.dumps(index, indent=2))

    # Commit + push
    ok = run_git(["git", "add", "-A"]) and \
         run_git(["git", "commit", "-m", f"Start {session_name} session {today} (in-progress)"]) and \
         run_git(["git", "push", "origin", "main"])

    if not ok:
        print("WARNING: git commit/push may have failed — inspect manually.", file=sys.stderr)

    # Print presentation-ready table
    print(f"SESSION_STARTED|{session_type}|{session_name}|{today}|{now_hm}")
    for e in exercises:
        w = f"{e['target_weight_kg']}kg" if e['target_weight_kg'] else "BW"
        print(f"  | {e['num']} | {e['name']} | {e['target_sets']} | {w} | {e['target_reps']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())