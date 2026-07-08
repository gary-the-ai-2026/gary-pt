#!/usr/bin/env python3
"""Recalibrate bar weights across all session logs."""
import json, os, glob

LOGS_DIR = "/Users/gary/Projects/gary-pt/logs"

SMITH_RENAME = {
    "Barbell Back Squat": "Smith Machine Squat",
    "Barbell Bench Press": "Smith Machine Bench Press",
    "Incline Barbell Bench Press": "Incline Smith Machine Bench Press",
}
SMITH_ADD_BAR = ["Smith Machine Squat", "Smith Machine Bench Press", "Incline Smith Machine Bench Press"]
BARBELL_ADD_BAR = ["Barbell Row", "Barbell Curl", "Romanian Deadlift (BB)"]

log_files = sorted(glob.glob(os.path.join(LOGS_DIR, "*.json")))
log_files = [f for f in log_files if os.path.basename(f) not in ("index.json", "_template.json")]

changes = []
for fp in log_files:
    with open(fp, 'r') as f:
        data = json.load(f)
    modified = False
    fname = os.path.basename(fp)
    for ex in data.get("exercises", []):
        name = ex.get("name", "")
        if name in SMITH_RENAME:
            old = name
            ex["name"] = SMITH_RENAME[name]
            name = ex["name"]
            modified = True
            for s in (ex.get("sets") or []):
                if s.get("weight_kg") is not None:
                    s["weight_kg"] += 15
            if ex.get("target_weight_kg") is not None:
                ex["target_weight_kg"] += 15
            changes.append(f"  {fname}: {old} → {name} (+15kg)")
        elif name in SMITH_ADD_BAR:
            for s in (ex.get("sets") or []):
                if s.get("weight_kg") is not None:
                    s["weight_kg"] += 15
            if ex.get("target_weight_kg") is not None:
                ex["target_weight_kg"] += 15
            modified = True
            changes.append(f"  {fname}: {name} (+15kg bar added)")
        elif name in BARBELL_ADD_BAR:
            for s in (ex.get("sets") or []):
                if s.get("weight_kg") is not None:
                    s["weight_kg"] += 20
            if ex.get("target_weight_kg") is not None:
                ex["target_weight_kg"] += 20
            modified = True
            changes.append(f"  {fname}: {name} (+20kg bar added)")
    if modified:
        existing = data.get("notes", "")
        recal = "2026-07-08: Bar weight recalibration — Smith +15kg, barbell +20kg added to all weights."
        data["notes"] = f"{existing}\n{recal}" if existing else recal
        with open(fp, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')

print(f"Modified {len(set(os.path.basename(f) for c in changes for f in [c.split(':')[0].strip()]))} files:")
for c in changes:
    print(c)
