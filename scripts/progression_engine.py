#!/usr/bin/env python3
"""
PT Gary — Progression Engine
Reads completed session logs, applies progression rules, updates program weights.

Rules:
  - All sets hit top of rep range → +2.5kg (upper) or +5kg (lower)
  - Some sets hit top → repeat weight
  - Missed 2+ sets → -5%
  - 2 consecutive stalls → flag exercise rotation
  - DBs maxed at 27kg → add reps, then add set, then swap

Usage:
  python3 progression_engine.py
  (called automatically after each voice session completes)
"""

import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

ADL = timezone(timedelta(hours=9, minutes=30))
REPO = Path("/Users/gary/Projects/gary-pt")
PROGRAM_FILE = REPO / "programs" / "cycle-1-week-1.md"
CONFIG_FILE = REPO / "config" / "josh-hancock.md"
STALL_FILE = REPO / "programs" / ".stall_tracker.json"

# ── Parse Helpers ────────────────────────────────────────────────────────────

def parse_log_file(filepath: Path) -> dict:
    """Parse a completed session log into structured data."""
    content = filepath.read_text()
    lines = content.split('\n')

    # Extract metadata from frontmatter
    frontmatter = {}
    in_frontmatter = False
    for line in lines:
        if line.strip() == '---':
            if not in_frontmatter:
                in_frontmatter = True
                continue
            else:
                break
        if in_frontmatter and ':' in line:
            key, val = line.split(':', 1)
            frontmatter[key.strip()] = val.strip()

    # Parse exercise table
    exercises = {}
    in_table = False
    for line in lines:
        if line.startswith('| # | Exercise'):
            in_table = True
            continue
        if in_table and line.startswith('|'):
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if len(cells) >= 4 and cells[0] and cells[0].isdigit():
                name = cells[1]
                target = cells[2]
                actual = cells[3]
                exercises[name] = {
                    "target": target,
                    "actual": actual,
                }

    return {
        "session_type": frontmatter.get("type", ""),
        "date": frontmatter.get("date", ""),
        "exercises": exercises,
    }


def parse_target(target: str) -> dict:
    """Parse '80kg × 8–10' → {weight: 80, rep_low: 8, rep_high: 10}"""
    result = {"weight": None, "rep_low": 8, "rep_high": 12}
    # Extract weight — the first number before 'kg'
    w = re.search(r'([\d.]+)\s*kg', target)
    if w:
        result["weight"] = float(w.group(1))

    # Extract rep range — numbers after the '×' or from the latter part
    # Split on '×' and parse the right side
    if '×' in target:
        rep_part = target.split('×')[-1]
    else:
        rep_part = target

    reps = re.findall(r'(\d+)', rep_part)
    if len(reps) >= 2:
        result["rep_low"] = int(reps[0])
        result["rep_high"] = int(reps[1])
    elif len(reps) == 1:
        result["rep_low"] = int(reps[0])
        result["rep_high"] = int(reps[0])
    return result


def parse_actual_sets(actual: str) -> list[int]:
    """Parse '80kg×10 / 80kg×10 / 80kg×9' → [10, 10, 9] or 'Skipped' → []"""
    if not actual or actual.lower() == 'skipped':
        return []
    reps = re.findall(r'×(\d+)', actual)
    return [int(r) for r in reps]


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
        import json
        stalls = json.loads(STALL_FILE.read_text())

    if action in ["repeat", "drop"]:
        stalls[exercise_name] = stalls.get(exercise_name, 0) + 1
    else:
        stalls[exercise_name] = 0

    import json
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
            # Pattern: | # | Exercise Name | Sets × Reps | OldWeight | Rest |
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
        log_files = sorted(logs_dir.glob("*.md"))
        log_files = [f for f in log_files if not f.name.startswith('_')]
        if not log_files:
            print("No session logs found.")
            return None
        log_file = log_files[-1]

    # Parse log
    session = parse_log_file(log_file)
    print(f"📊 Processing: {session['date']} — {session['session_type']}")

    results = {}
    for ex_name, data in session["exercises"].items():
        if not data["actual"] or data["actual"].lower() == "skipped":
            results[ex_name] = {"action": "skip", "new_weight": None, "reason": "Skipped"}
            continue

        target = parse_target(data["target"])
        actual_reps = parse_actual_sets(data["actual"])

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
    date_str = session["date"]
    type_str = session["session_type"]
    os.system(f"git commit -m 'progression: {date_str} {type_str}' 2>&1")
    os.system("git push origin main 2>&1")

    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_progression(Path(sys.argv[1]))
    else:
        run_progression()
