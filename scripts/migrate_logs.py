#!/usr/bin/env python3
"""Migrate existing MD session logs to JSON format.

Parses the old Markdown table format and produces structured JSON logs.
Run once, then delete the old .md files (or archive them).
"""
import re
import json
from pathlib import Path

LOGS_DIR = Path("/Users/gary/Projects/gary-pt/logs")


def parse_md_log(filepath: Path) -> dict:
    """Parse an existing MD session log into a JSON-format dict."""
    content = filepath.read_text()
    lines = content.split('\n')

    # Extract YAML frontmatter
    frontmatter = {}
    in_fm = False
    for line in lines:
        if line.strip() == '---':
            if not in_fm:
                in_fm = True
                continue
            else:
                break
        if in_fm and ':' in line:
            k, v = line.split(':', 1)
            frontmatter[k.strip()] = v.strip()

    # Extract metadata from body
    status = frontmatter.get("status", "complete")
    date_str = frontmatter.get("date", "")
    session_type = frontmatter.get("type", "")
    cycle = int(frontmatter.get("cycle", 1))
    week = int(frontmatter.get("week", 1))

    started = ""
    finished = ""
    duration_min = 0
    notes = ""

    # Extract timing
    for line in lines:
        if line.startswith("**Started:**"):
            started = line.split("**Started:**")[1].strip()
        elif line.startswith("**Finished:**"):
            finished = line.split("**Finished:**")[1].strip()
        elif line.startswith("**Duration:**"):
            dur = line.split("**Duration:**")[1].strip()
            m = re.match(r'(\d+)', dur)
            if m:
                duration_min = int(m.group(1))

    # Extract notes
    in_notes = False
    note_lines = []
    for line in lines:
        if line.startswith("**Notes:**"):
            in_notes = True
            note_content = line.split("**Notes:**", 1)[1].strip()
            if note_content:
                note_lines.append(note_content)
            continue
        if in_notes and line.strip() and not line.startswith("|"):
            note_lines.append(line.strip())
    notes = ' '.join(note_lines)

    # Parse exercise table
    exercises = []
    in_table = False
    headers = []
    log_col_idx = -1
    ex_num = 0

    for line in lines:
        if line.startswith('| # | Exercise') or line.startswith('|#|Exercise'):
            in_table = True
            headers = [c.strip() for c in line.split('|') if c.strip()]
            for i, h in enumerate(headers):
                if h.lower() == 'log':
                    log_col_idx = i
            continue
        if in_table and line.startswith('|'):
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if not cells or not cells[0].isdigit():
                continue

            ex_num += 1
            name = cells[1] if len(cells) > 1 else ""
            target_col = cells[2] if len(cells) > 2 else ""

            # Parse target: "3 × 8–12" or "3 × 8-10"
            target_sets = 3
            target_reps = "8-12"
            tmatch = re.match(r'(\d+)\s*[×x]\s*([\d–\-]+)', target_col)
            if tmatch:
                target_sets = int(tmatch.group(1))
                target_reps = tmatch.group(2).replace('–', '-')

            # Parse target weight from 4th column
            target_weight_kg = None
            if len(cells) > 3 and 'kg' in cells[3]:
                wm = re.search(r'([\d.]+)\s*kg', cells[3])
                if wm:
                    target_weight_kg = float(wm.group(1))

            # Parse log column for sets
            log_text = ""
            if log_col_idx >= 0 and len(cells) > log_col_idx:
                log_text = cells[log_col_idx]

            # Check if skipped
            if log_text.lower() == 'skipped' or re.match(r'skipped', log_text.lower()):
                exercises.append({
                    "num": ex_num,
                    "name": name,
                    "target_sets": target_sets,
                    "target_reps": target_reps,
                    "target_weight_kg": target_weight_kg,
                    "skipped": True,
                    "sets": None
                })
                continue

            # Parse sets: "Set 1: 32kg × 12 · Set 2: 36kg × 12"
            set_matches = re.findall(
                r'Set\s*(\d+):\s*([\d.]+)kg\s*[×x]\s*(\d+)',
                log_text,
                re.IGNORECASE
            )
            if not set_matches:
                # Try alternate: "80kg×10 / 80kg×9"
                alt = re.findall(r'([\d.]+)kg\s*[×x]\s*(\d+)', log_text)
                set_matches = [(str(i+1), w, r) for i, (w, r) in enumerate(alt)]

            sets = [
                {"set": int(s), "weight_kg": float(w), "reps": int(r)}
                for s, w, r in set_matches
            ]

            exercises.append({
                "num": ex_num,
                "name": name,
                "target_sets": target_sets,
                "target_reps": target_reps,
                "target_weight_kg": target_weight_kg,
                "skipped": False,
                "sets": sets
            })

    # If no table found but frontmatter had it, try body parsing
    if not exercises:
        # Parse from body lines for old format
        for line in lines:
            if re.match(r'^\d+\.\s+', line.strip()):
                # "1. Barbell Bench: 80×10/80×10/80×9"
                m = re.match(r'(\d+)\.\s+(.+?):\s*(.+)', line.strip())
                if m:
                    ex_num += 1
                    name = m.group(2).strip()
                    data = m.group(3).strip()
                    if data.lower() == 'skipped':
                        exercises.append({
                            "num": ex_num, "name": name,
                            "target_sets": 3, "target_reps": "8-12",
                            "target_weight_kg": None,
                            "skipped": True, "sets": None
                        })
                    else:
                        sets_data = re.findall(r'([\d.]+)[×x](\d+)', data)
                        exercises.append({
                            "num": ex_num, "name": name,
                            "target_sets": 3, "target_reps": "8-12",
                            "target_weight_kg": None,
                            "skipped": False,
                            "sets": [
                                {"set": i+1, "weight_kg": float(w), "reps": int(r)}
                                for i, (w, r) in enumerate(sets_data)
                            ]
                        })

    return {
        "session_id": f"{date_str}-{session_type}",
        "date": date_str,
        "type": session_type,
        "status": status.lower().replace(" ", "_") if status else "complete",
        "started": started,
        "finished": finished,
        "duration_min": duration_min,
        "cycle": cycle,
        "week": week,
        "exercises": exercises,
        "notes": notes
    }


def migrate_all():
    md_files = sorted(LOGS_DIR.glob("*.md"))
    md_files = [f for f in md_files if not f.name.startswith('_')]

    for md_file in md_files:
        json_file = md_file.with_suffix('.json')
        if json_file.exists():
            print(f"  Skipping (already exists): {json_file.name}")
            continue

        print(f"  Converting: {md_file.name} → {json_file.name}")
        try:
            data = parse_md_log(md_file)
            json_file.write_text(json.dumps(data, indent=2))
            print(f"    ✓ {len(data['exercises'])} exercises, {'skipped' if any(e.get('skipped') for e in data['exercises']) else 'all complete'}")
        except Exception as e:
            print(f"    ✗ Error: {e}")

    # Create _template.json
    template = LOGS_DIR / "_template.json"
    if not template.exists():
        template.write_text(json.dumps({
            "session_id": "YYYY-MM-DD-{type}",
            "date": "YYYY-MM-DD",
            "type": "chest-tri | back-bi | legs-shoulders",
            "status": "complete",
            "started": "",
            "finished": "",
            "duration_min": 0,
            "cycle": 1,
            "week": 1,
            "exercises": [],
            "notes": ""
        }, indent=2))
        print(f"\n  Created _template.json")


if __name__ == "__main__":
    print("Migrating MD logs → JSON...\n")
    migrate_all()
    print("\nDone. Old .md files can be archived or deleted.")
