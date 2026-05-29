#!/usr/bin/env python3
"""
PT Gary — Progression Engine
Reads completed session logs (JSON), applies progression rules, updates program weights.

Rules:
  - All sets hit top of rep range → +2.5kg (upper) or +5kg (lower)
  - Some sets hit top → repeat weight
  - Missed 2+ sets → -5%
  - 2 consecutive stalls → flag exercise rotation
  - DBs maxed at 27kg → add reps, then add set, then swap

Usage:
  python3 progression_engine.py [path/to/session.json]
  (called automatically after each session completes)
"""

import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ADL = timezone(timedelta(hours=9, minutes=30))
REPO = Path("/Users/gary/Projects/gary-pt")
PROGRAM_FILE = REPO / "programs" / "cycle-1-week-1.md"
CONFIG_FILE = REPO / "config" / "josh-hancock.md"
STALL_FILE = REPO / "programs" / ".stall_tracker.json"


# ── Parse Helpers ────────────────────────────────────────────────────────────

def parse_log_file(filepath: Path) -> dict:
    """Parse a completed session JSON log into structured data."""
    return json.loads(filepath.read_text())


def parse_target_from_exercise(exercise: dict) -> dict:
    """Parse exercise JSON into target dict: {weight, rep_low, rep_high}.

    Uses the structured fields from the JSON log format:
      target_weight_kg, target_reps, target_sets
    """
    t = {
        "weight": exercise.get("target_weight_kg"),
        "rep_low": 8,
        "rep_high": 12,
    }

    reps_str = exercise.get("target_reps", "")
    if reps_str and '-' in reps_str:
        parts = reps_str.split('-')
        t["rep_low"] = int(parts[0].strip())
        t["rep_high"] = int(parts[1].strip())
    elif reps_str:
        v = int(reps_str.strip())
        t["rep_low"] = v
        t["rep_high"] = v

    return t


def actual_reps_from_exercise(exercise: dict) -> list[int]:
    """Extract reps from exercise's sets array."""
    if exercise.get("skipped"):
        return []
    sets = exercise.get("sets") or []
    return [s["reps"] for s in sets if "reps" in s]


# ── Progression Logic ─────────────────────────────────────────────────────────

LOWER_BODY = {"squat", "deadlift", "rdl", "romanian", "leg press", "leg extension",
              "leg curl", "bulgarian", "split squat", "lunge", "calf raise",
              "hip thrust", "glute bridge"}


def is_lower(exercise_name: str) -> bool:
    """Check if an exercise is lower body (deserves +5kg bumps)."""
    name_lower = exercise_name.lower()
    return any(lb in name_lower for lb in LOWER_BODY)


def calculate_progression(target: dict, actual_reps: list[int], exercise_name: str) -> dict:
    """Calculate the new weight for an exercise based on actual performance.

    Returns: {"action": "bump"|"repeat"|"drop"|"skip", "new_weight": float|None, "reason": str}
    """
    if not actual_reps or all(r == 0 for r in actual_reps):
        return {"action": "skip", "new_weight": target["weight"], "reason": "Exercise skipped"}

    rep_high = target["rep_high"]
    rep_low = target["rep_low"]
    weight = target["weight"]

    # Count how many sets hit the top of the rep range
    sets_hit_top = sum(1 for r in actual_reps if r >= rep_high)
    sets_missed_bottom = sum(1 for r in actual_reps if r < rep_low)
    total_sets = len(actual_reps)

    if sets_hit_top == total_sets:
        # All sets hit top → bump weight
        bump = 5.0 if is_lower(exercise_name) else 2.5
        new_weight = (weight or 0) + bump
        return {"action": "bump", "new_weight": new_weight, "reason": f"All {total_sets} sets hit ≥{rep_high} reps: +{bump}kg"}

    if sets_missed_bottom >= 2:
        # Two or more sets below bottom → drop
        new_weight = round((weight or 0) * 0.95, 1)
        return {"action": "drop", "new_weight": new_weight, "reason": f"{sets_missed_bottom} sets below {rep_low} reps: −5%"}

    if sets_hit_top > 0:
        # Some sets hit top → repeat
        return {"action": "repeat", "new_weight": weight, "reason": f"Partial completion ({sets_hit_top}/{total_sets} sets hit top): repeat weight"}

    # All sets within range but none at top → repeat
    return {"action": "repeat", "new_weight": weight, "reason": f"All sets within {rep_low}–{rep_high} range: repeat weight"}


# ── Stall Detection ────────────────────────────────────────────────────────────

def check_stalls(exercise_name: str, action: str) -> bool:
    """Track stall history and flag if 2 consecutive stalls on same exercise."""
    stalls = {}
    if STALL_FILE.exists():
        stalls = json.loads(STALL_FILE.read_text())

    if action in ["repeat", "drop"]:
        stalls[exercise_name] = stalls.get(exercise_name, 0) + 1
    else:
        stalls[exercise_name] = 0

    STALL_FILE.write_text(json.dumps(stalls, indent=2))

    return stalls[exercise_name] >= 2


# ── Program Updater ────────────────────────────────────────────────────────────

def update_program_weights(progression_results: dict):
    """Update the program MD file with new weights based on progression results."""
    content = PROGRAM_FILE.read_text()

    for ex_name, result in progression_results.items():
        if result["action"] in ["bump", "drop"] and result["new_weight"] is not None:
            new_weight_str = f"{result['new_weight']}kg"

            # Find and replace the weight for this exercise in the program
            # Pattern: full cell containing exercise name followed by weight
            escaped = re.escape(ex_name)
            pattern = rf'(\|.*?{escaped}.*?\|\s*[\d.]+kg)'
            replacement = lambda m: m.group(0).replace(
                re.search(r'[\d.]+kg', m.group(0)).group(0),
                new_weight_str
            ) if re.search(r'[\d.]+kg', m.group(0)) else m.group(0)

            content = re.sub(pattern, replacement, content)

    PROGRAM_FILE.write_text(content)
    return content


# ── Main ───────────────────────────────────────────────────────────────────────

def run_progression(latest_log_path: Path = None):
    """Run the full progression engine on the latest session log.

    If latest_log_path is provided, use that. Otherwise find the most recent log.
    """
    # Find latest log
    logs_dir = REPO / "logs"
    if latest_log_path:
        log_file = latest_log_path
    else:
        log_files = sorted(logs_dir.glob("*.json"))
        log_files = [f for f in log_files if not f.name.startswith('_')]
        if not log_files:
            print("No session logs found.")
            return None
        log_file = log_files[-1]

    # Parse log
    session = parse_log_file(log_file)
    session_type = session.get("type", "")
    session_date = session.get("date", "")
    print(f"📊 Processing: {session_date} — {session_type}")

    results = {}
    for ex in session.get("exercises", []):
        ex_name = ex["name"]
        if ex.get("skipped"):
            results[ex_name] = {"action": "skip", "new_weight": None, "reason": "Skipped"}
            continue

        target = parse_target_from_exercise(ex)
        actual_reps = actual_reps_from_exercise(ex)

        if not actual_reps:
            continue

        result = calculate_progression(target, actual_reps, ex_name)
        results[ex_name] = result

        # Check stalls
        is_stalled = check_stalls(ex_name, result["action"])
        if is_stalled:
            result["stalled"] = True
            result["reason"] += " ⚠️ STALLED — consider exercise rotation"

        flag = "✓" if result["action"] == "bump" else "⚠️" if result["action"] == "drop" else "—"
        weight_str = f"→ {result['new_weight']}kg" if result["new_weight"] else ""
        print(f"  {flag} {ex_name}: {result['reason']} {weight_str}")

    # Update program
    update_program_weights(results)

    # Commit
    import os
    os.chdir(REPO)
    os.system("git add programs/cycle-1-week-1.md programs/.stall_tracker.json 2>/dev/null")
    os.system(f"git commit -m 'progression: {session_date} {session_type}' 2>&1")
    os.system("git push origin main 2>&1")

    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_progression(Path(sys.argv[1]))
    else:
        run_progression()
