#!/usr/bin/env python3
"""PT Gary — Workout Log Parser

Parses Telegram shorthand messages into structured workout logs.
Run standalone or called by Hermes when Josh sends log messages.

Usage:
    python3 parse_workout.py "bench 80 10/10/9"
    python3 parse_workout.py "incline db 28 12/12/11, pushdown 25 15/14/12"
    python3 parse_workout.py "bw 84.5"
"""

import sys
import re
from datetime import datetime, timezone, timedelta

# Adelaide timezone
ADL = timezone(timedelta(hours=9, minutes=30))

# Exercise name aliases → canonical names from exercise library
EXERCISE_ALIASES = {
    # Bench variants
    "bench": "Barbell Bench Press",
    "bb bench": "Barbell Bench Press",
    "barbell bench": "Barbell Bench Press",
    "flat bench": "Barbell Bench Press",
    "incline bb": "Incline Barbell Bench",
    "incline barbell": "Incline Barbell Bench",
    "decline bench": "Decline Barbell Bench",
    "db bench": "Dumbbell Bench Press",
    "dumbbell bench": "Dumbbell Bench Press",
    "incline db": "Incline Dumbbell Press",
    "incline dumbbell": "Incline Dumbbell Press",
    # Shoulder press
    "ohp": "Barbell Overhead Press",
    "overhead press": "Barbell Overhead Press",
    "shoulder press": "Barbell Overhead Press",
    "db shoulder press": "Dumbbell Shoulder Press",
    "db press": "Dumbbell Shoulder Press",
    "arnold press": "Arnold Press",
    # Flyes
    "cable flye": "Cable Flye (Mid)",
    "cable fly": "Cable Flye (Mid)",
    "flye": "Cable Flye (Mid)",
    "high fly": "Cable Flye (High)",
    "low fly": "Cable Flye (Low)",
    "db flye": "Dumbbell Flye",
    "pec deck": "Pec Deck",
    # Lateral raise
    "lateral raise": "Dumbbell Lateral Raise",
    "lat raise": "Dumbbell Lateral Raise",
    "side raise": "Dumbbell Lateral Raise",
    "cable lateral": "Cable Lateral Raise",
    "front raise": "Front Raise",
    # Face pull
    "face pull": "Face Pull",
    "reverse pec": "Reverse Pec Deck",
    "rear delt": "Reverse Pec Deck",
    # Triceps
    "pushdown": "Tricep Pushdown (Rope)",
    "tricep pushdown": "Tricep Pushdown (Rope)",
    "tri pushdown": "Tricep Pushdown (Rope)",
    "rope pushdown": "Tricep Pushdown (Rope)",
    "overhead extension": "Overhead Cable Extension",
    "overhead tri": "Overhead Cable Extension",
    "skull crusher": "Skull Crusher",
    "skulls": "Skull Crusher",
    "dips": "Dips",
    "kickback": "Single-Arm Cable Kickback",
    "bench dip": "Bench Dip",
    "db overhead extension": "Dumbbell Overhead Extension",
    "close grip": "Close-Grip Bench Press",
    # Squat
    "squat": "Barbell Back Squat",
    "back squat": "Barbell Back Squat",
    "front squat": "Front Squat",
    "goblet squat": "Goblet Squat",
    "goblet": "Goblet Squat",
    "bulgarian": "Bulgarian Split Squat",
    "split squat": "Bulgarian Split Squat",
    "bss": "Bulgarian Split Squat",
    "lunge": "Walking Lunge",
    "lunges": "Walking Lunge",
    "smith squat": "Smith Machine Squat",
    # Deadlift
    "deadlift": "Conventional Deadlift",
    "rdl": "Romanian Deadlift (DB)",
    "romanian": "Romanian Deadlift (DB)",
    "sumo": "Sumo Deadlift",
    "trap bar": "Trap Bar Deadlift",
    # Leg press / extension / curl
    "leg press": "Leg Press",
    "leg extension": "Leg Extension",
    "leg curl": "Lying Leg Curl",
    "hamstring curl": "Lying Leg Curl",
    "seated curl": "Seated Leg Curl",
    # Glutes
    "hip thrust": "Hip Thrust",
    "glute bridge": "Glute Bridge",
    "kickback cable": "Cable Kickback",
    # Calves
    "calf raise": "Standing Calf Raise",
    "seated calf": "Seated Calf Raise",
    # Pull
    "lat pulldown": "Lat Pulldown (Wide)",
    "pulldown": "Lat Pulldown (Wide)",
    "wide pulldown": "Lat Pulldown (Wide)",
    "close pulldown": "Lat Pulldown (Close)",
    "neutral pulldown": "Lat Pulldown (Neutral)",
    "pullup": "Pull-Up",
    "pull up": "Pull-Up",
    "chinup": "Chin-Up",
    "chin up": "Chin-Up",
    # Rows
    "barbell row": "Barbell Row",
    "bb row": "Barbell Row",
    "db row": "Dumbbell Row (Single Arm)",
    "dumbbell row": "Dumbbell Row (Single Arm)",
    "cable row": "Seated Cable Row (Close)",
    "seated row": "Seated Cable Row (Close)",
    "tbar": "T-Bar Row",
    "t bar": "T-Bar Row",
    "meadows row": "Meadows Row",
    # Biceps
    "barbell curl": "Barbell Curl",
    "bb curl": "Barbell Curl",
    "db curl": "Dumbbell Curl",
    "dumbbell curl": "Dumbbell Curl",
    "incline curl": "Incline Dumbbell Curl",
    "hammer curl": "Hammer Curl",
    "preacher curl": "Preacher Curl",
    "cable curl": "Cable Curl",
    "concentration curl": "Concentration Curl",
    # Core
    "cable crunch": "Cable Crunch",
    "leg raise": "Hanging Leg Raise",
    "ab wheel": "Ab Wheel Rollout",
    "plank": "Plank",
    "pallof": "Pallof Press",
}


def parse_weight_reps(text: str) -> tuple[float | None, list[int], str | None]:
    """Parse '80 10/10/9' or 'bodyweight 12/12/12' or '28/side 12/12/11'.

    Returns (weight_kg, [reps], unit_note).
    weight_kg is None for bodyweight exercises.
    """
    text = text.strip()

    # Bodyweight
    if text.lower().startswith(("bw", "bodyweight", "body weight")):
        rest = re.sub(r'^(bw|bodyweight|body weight)\s*', '', text, flags=re.IGNORECASE)
        reps = parse_reps(rest) if rest else []
        return (None, reps, "BW")

    # Weight with /side notation: "28/side 12/12/11"
    side_match = re.match(r'^([\d.]+)\s*/side\s*(.*)', text, re.IGNORECASE)
    if side_match:
        weight = float(side_match.group(1))
        reps = parse_reps(side_match.group(2)) if side_match.group(2).strip() else []
        return (weight, reps, "/side")

    # Standard: "80 10/10/9" or "80kg 10/10/9"
    m = re.match(r'^([\d.]+)\s*(?:kg)?\s*(.*)', text, re.IGNORECASE)
    if m:
        weight = float(m.group(1))
        reps = parse_reps(m.group(2)) if m.group(2).strip() else []
        return (weight, reps, None)

    return (None, [], None)


def parse_reps(text: str) -> list[int]:
    """Parse '10/10/9' or '10,10,9' or '10 10 9' into [10, 10, 9]."""
    text = text.strip()
    # Try slash-separated
    if '/' in text:
        parts = text.split('/')
    # Try comma-separated
    elif ',' in text:
        parts = text.split(',')
    # Try space-separated
    else:
        parts = text.split()

    reps = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            reps.append(int(p))
        else:
            # Handle "10+" or "10+" notation (AMRAP)
            clean = re.sub(r'[^0-9]', '', p)
            if clean.isdigit():
                reps.append(int(clean))
    return reps


def parse_exercise_line(line: str) -> dict | None:
    """Parse a single exercise log line.

    Format: "<exercise_alias> <weight> <reps/reps/reps>"

    Returns dict with canonical_name, weight, reps, unit_note, or None if unparseable.
    """
    line = line.strip()
    if not line:
        return None

    # Try to match an exercise alias at the start
    matched_alias = None
    matched_name = None

    # Sort aliases by length (longest first) to match "incline db" before "db"
    sorted_aliases = sorted(EXERCISE_ALIASES.keys(), key=len, reverse=True)

    for alias in sorted_aliases:
        if line.lower().startswith(alias.lower()):
            matched_alias = alias
            matched_name = EXERCISE_ALIASES[alias]
            break

    if not matched_alias:
        return None

    # Extract the remainder after the alias
    remainder = line[len(matched_alias):].strip()
    weight, reps, unit = parse_weight_reps(remainder)

    return {
        "alias": matched_alias,
        "canonical_name": matched_name,
        "weight_kg": weight,
        "reps": reps,
        "unit_note": unit,
    }


def parse_bodyweight(text: str) -> float | None:
    """Parse 'bw 84.5' → 84.5"""
    m = re.match(r'^(?:bw|bodyweight|body weight)\s+([\d.]+)', text.strip(), re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def parse_message(text: str) -> dict:
    """Main entry point. Parse a full Telegram message into structured workout data.

    Returns:
        {
            "type": "workout_log" | "bodyweight" | "session_note" | "unknown",
            "exercises": [...],
            "bodyweight": float | None,
            "session": "push" | "pull" | "legs" | None,
            "notes": str | None,
        }
    """
    result = {
        "type": "unknown",
        "exercises": [],
        "bodyweight": None,
        "session": None,
        "notes": None,
    }

    text = text.strip()

    # Check for bodyweight
    bw = parse_bodyweight(text)
    if bw:
        result["type"] = "bodyweight"
        result["bodyweight"] = bw
        return result

    # Check for session declaration
    session_lower = text.lower()
    for s in ["chest", "back", "legs", "push", "pull"]:
        if re.search(rf'\b{s}\b', session_lower):
            if s == "chest":
                result["session"] = "chest-tri"
            elif s == "back":
                result["session"] = "back-bi"
            elif s == "legs":
                result["session"] = "legs-shoulders"
            elif s == "push":
                result["session"] = "chest-tri"
            elif s == "pull":
                result["session"] = "back-bi"
            break

    if text.lower() in ["chest", "back", "legs", "push", "pull", "chest-tri", "back-bi", "legs-shoulders", "chest/tri", "back/bi", "legs/shoulders"]:
        result["type"] = "session_start"
        return result

    if text.lower().endswith(("done", "complete", "finished")):
        result["type"] = "session_complete"
        return result

    # Parse exercises — split on comma or newline
    lines = [l.strip() for l in re.split(r'[,;\n]+', text) if l.strip()]

    for line in lines:
        ex = parse_exercise_line(line)
        if ex:
            result["exercises"].append(ex)

    if result["exercises"]:
        result["type"] = "workout_log"

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 parse_workout.py '<message>'")
        sys.exit(1)

    msg = " ".join(sys.argv[1:])
    result = parse_message(msg)
    import json
    print(json.dumps(result, indent=2))
