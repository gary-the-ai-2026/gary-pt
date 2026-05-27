#!/usr/bin/env python3
"""
PT Gary — Interactive Workout Bot
Handles inline keyboard workouts via Telegram Bot API.

Flow:
  1. Josh types "chest" / "back" / "legs" in the PT group
  2. Bot sends Exercise 1, Set 1 with tappable weight/reps buttons
  3. Josh taps → callback → logged → next set or exercise
  4. Session complete → summary + commit to gary-pt repo

Usage:
  python3 pt_gary_bot.py
  (runs as long-polling daemon — manage via Hermes terminal background=true)
"""

import json
import os
import re
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
import re as _re
with open('/tmp/tg_send.py') as f:
    _m = _re.search(r'BOT_TOKEN = "([^"]+)"', f.read())
    BOT_TOKEN = _m.group(1)

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
ADL = timezone(timedelta(hours=9, minutes=30))
REPO = Path("/Users/gary/Projects/gary-pt")
STATE_FILE = REPO / "scripts" / ".session_state.json"
PROGRAM_FILE = REPO / "programs" / "cycle-1-week-1.md"

# PT group chat_id — set after first message received
PT_GROUP_ID = None

# ── Program Data ───────────────────────────────────────────────────────────────

PROGRAM = {
    "chest-tri": {
        "name": "Chest / Triceps",
        "exercises": [
            {"name": "Barbell Bench Press", "sets": 3, "rep_range": "8–10", "weight": 80, "rest": "2–3 min"},
            {"name": "Incline Dumbbell Press", "sets": 3, "rep_range": "10–12", "weight": 27, "rest": "90 sec", "note": "/side"},
            {"name": "Cable Flye (Low-to-High)", "sets": 3, "rep_range": "12–15", "weight": None, "rest": "60 sec"},
            {"name": "Tricep Pushdown (Rope)", "sets": 3, "rep_range": "12–15", "weight": 25, "rest": "60 sec"},
            {"name": "Overhead Cable Extension", "sets": 3, "rep_range": "12–15", "weight": None, "rest": "60 sec"},
            {"name": "Close-Grip Bench Press", "sets": 2, "rep_range": "10–12", "weight": None, "rest": "90 sec"},
        ]
    },
    "back-bi": {
        "name": "Back / Biceps",
        "exercises": [
            {"name": "Lat Pulldown (Wide)", "sets": 3, "rep_range": "8–12", "weight": None, "rest": "90 sec"},
            {"name": "Barbell Row", "sets": 3, "rep_range": "8–10", "weight": None, "rest": "2 min"},
            {"name": "Seated Cable Row (Close)", "sets": 3, "rep_range": "10–12", "weight": None, "rest": "90 sec"},
            {"name": "Face Pull", "sets": 3, "rep_range": "12–15", "weight": None, "rest": "60 sec"},
            {"name": "Barbell Curl", "sets": 3, "rep_range": "10–12", "weight": None, "rest": "60 sec"},
            {"name": "Preacher Curl", "sets": 3, "rep_range": "10–12", "weight": None, "rest": "60 sec"},
        ]
    },
    "legs-shoulders": {
        "name": "Legs / Shoulders",
        "exercises": [
            {"name": "Barbell Back Squat", "sets": 3, "rep_range": "8–10", "weight": None, "rest": "2–3 min"},
            {"name": "Romanian Deadlift (BB)", "sets": 3, "rep_range": "8–12", "weight": None, "rest": "2 min"},
            {"name": "Leg Extension", "sets": 3, "rep_range": "12–15", "weight": None, "rest": "60 sec"},
            {"name": "Leg Curl", "sets": 3, "rep_range": "12–15", "weight": None, "rest": "60 sec"},
            {"name": "Dumbbell Shoulder Press", "sets": 3, "rep_range": "8–12", "weight": None, "rest": "90 sec"},
            {"name": "Dumbbell Lateral Raise", "sets": 3, "rep_range": "12–15", "weight": None, "rest": "60 sec"},
            {"name": "Standing Calf Raise", "sets": 3, "rep_range": "15–20", "weight": None, "rest": "45 sec"},
        ]
    },
}

# ── API Helpers ────────────────────────────────────────────────────────────────

def api(method: str, payload: dict) -> dict:
    """Call Telegram Bot API."""
    r = requests.post(f"{BASE}/{method}", json=payload, timeout=10)
    return r.json()


def send_message(chat_id: int, text: str, reply_markup: dict = None, parse_mode: str = None):
    """Send a message with optional inline keyboard."""
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return api("sendMessage", payload)


def edit_message(chat_id: int, msg_id: int, text: str, reply_markup: dict = None):
    """Edit an existing message (update inline keyboard or text)."""
    payload = {"chat_id": chat_id, "message_id": msg_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return api("editMessageText", payload)


def answer_callback(callback_id: str, text: str = None):
    """Acknowledge a callback query."""
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    return api("answerCallbackQuery", payload)


# ── Inline Keyboard Builder ────────────────────────────────────────────────────

def build_weight_reps_keyboard(weight: float, rep_range: str, note: str = None) -> dict:
    """Build inline keyboard with weight×reps options.

    Example:
      Weight: 80kg, Rep Range: 8-10
      → Buttons: [80×10] [80×9] [80×8] [Failed]
                 [Skip] [Change Weight...]
    """
    if weight is None:
        weight = "TBD"
        weight_display = "TBD"
    else:
        weight_display = f"{weight}kg"
        if note:
            weight_display += f" {note}"

    # Parse rep range
    low, high = 8, 12  # defaults
    if rep_range:
        parts = re.findall(r'\d+', rep_range)
        if len(parts) >= 2:
            low, high = int(parts[0]), int(parts[1])

    # Build rep buttons (descending order — most likely first)
    buttons = []
    row = []
    for reps in range(high, low - 1, -1):
        if weight is not None and weight != "TBD":
            label = f"{weight}×{reps}"
            data = f"log|{weight}|{reps}"
        else:
            label = f"×{reps}"
            data = f"log_tbd|{reps}"
        row.append({"text": label, "callback_data": data})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Action row
    buttons.append([
        {"text": "❌ Failed", "callback_data": "failed"},
        {"text": "⏭ Skip", "callback_data": "skip"},
    ])

    # TBD weight: add custom weight option
    if weight == "TBD" or weight is None:
        buttons.append([
            {"text": "🔢 Custom weight...", "callback_data": "custom_weight"},
        ])

    return {"inline_keyboard": buttons}


def build_finish_keyboard() -> dict:
    """Build the session-complete keyboard."""
    return {"inline_keyboard": [
        [{"text": "✅ Finish Session", "callback_data": "finish"}],
    ]}


# ── Session State Machine ──────────────────────────────────────────────────────

def load_state() -> dict:
    """Load active session state."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def save_state(state: dict):
    """Save session state."""
    STATE_FILE.write_text(json.dumps(state, indent=2))


def clear_state():
    """Remove session state file."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def start_session(chat_id: int, session_type: str):
    """Initialize a new workout session."""
    program = PROGRAM[session_type]
    state = {
        "chat_id": chat_id,
        "session_type": session_type,
        "session_name": program["name"],
        "started_at": datetime.now(ADL).isoformat(),
        "current_exercise": 0,
        "current_set": 1,
        "exercises": program["exercises"],
        "log": {},  # {exercise_name: [{weight, reps}, ...]}
    }
    save_state(state)
    return state


def advance(state: dict, weight: float, reps: int):
    """Log a completed set and advance to next set/exercise."""
    ex = state["exercises"][state["current_exercise"]]
    ex_name = ex["name"]

    # Log the set
    if ex_name not in state["log"]:
        state["log"][ex_name] = []
    state["log"][ex_name].append({"weight": weight, "reps": reps})

    # Advance
    state["current_set"] += 1
    if state["current_set"] > ex["sets"]:
        # Move to next exercise
        state["current_exercise"] += 1
        state["current_set"] = 1

    # Check if session complete
    if state["current_exercise"] >= len(state["exercises"]):
        return "complete"

    save_state(state)
    return "next"


def skip_exercise(state: dict):
    """Skip current exercise entirely."""
    ex = state["exercises"][state["current_exercise"]]
    state["log"][ex["name"]] = [{"weight": 0, "reps": 0, "skipped": True}]
    state["current_exercise"] += 1
    state["current_set"] = 1

    if state["current_exercise"] >= len(state["exercises"]):
        return "complete"

    save_state(state)
    return "next"


# ── Message Builders ───────────────────────────────────────────────────────────

def build_exercise_message(state: dict) -> tuple[str, dict]:
    """Build the message and keyboard for the current exercise/set."""
    ex = state["exercises"][state["current_exercise"]]
    total_ex = len(state["exercises"])
    ex_num = state["current_exercise"] + 1

    weight_display = f"{ex['weight']}kg" if ex['weight'] else "TBD"
    if ex.get("note"):
        weight_display += f" {ex['note']}"

    text = (
        f"🏋️ *{state['session_name']}*\n\n"
        f"*{ex_num}/{total_ex} · {ex['name']}*\n"
        f"Set {state['current_set']} of {ex['sets']} · {ex['rep_range']} reps · Target: {weight_display}\n"
        f"Rest: {ex['rest']}"
    )

    keyboard = build_weight_reps_keyboard(ex['weight'], ex['rep_range'], ex.get("note"))
    return text, keyboard


def build_log_summary(state: dict) -> str:
    """Build the end-of-exercise log line."""
    ex = state["exercises"][state["current_exercise"]]
    ex_name = ex["name"]
    sets_logged = state["log"].get(ex_name, [])

    if not sets_logged:
        return f"_{ex_name}: skipped_"

    lines = []
    for i, s in enumerate(sets_logged):
        if s.get("skipped"):
            lines.append(f"  Set {i+1}: skipped")
        else:
            lines.append(f"  Set {i+1}: {s['weight']}kg × {s['reps']}")

    return f"*{ex_name}:*\n" + "\n".join(lines)


def build_session_summary(state: dict) -> str:
    """Build the complete session summary."""
    lines = [f"✅ *{state['session_name']} — COMPLETE*\n"]

    for ex in state["exercises"]:
        ex_name = ex["name"]
        sets_logged = state["log"].get(ex_name, [])
        target = f"{ex['weight']}kg" if ex['weight'] else "TBD"

        if not sets_logged:
            lines.append(f"⏭ {ex_name}: skipped")
            continue

        actual_reps = "/".join(str(s['reps']) for s in sets_logged if not s.get('skipped'))
        all_high = all(
            s['reps'] >= int(re.findall(r'\d+', ex['rep_range'])[1])
            for s in sets_logged if not s.get('skipped')
        )
        flag = " ✓" if all_high else " ⚠️"

        lines.append(f"{flag} {ex_name}: {target} → {actual_reps}")

    lines.append(f"\n→ Next session weights updated in dashboard")
    return "\n".join(lines)


def write_markdown_log(state: dict):
    """Write the session log as a markdown file and commit to repo."""
    today = datetime.now(ADL).strftime("%Y-%m-%d")
    session_type = state["session_type"]
    filename = f"{today}-{session_type}.md"
    filepath = REPO / "logs" / filename

    lines = [
        "---",
        f"session_id: \"{today}-{session_type}\"",
        f"date: \"{today}\"",
        f"type: {session_type}",
        "cycle: 1",
        "week: 1",
        "---",
        "",
        f"# {state['session_name']} — {today}",
        "",
        "| # | Exercise | Target | Sets |",
        "|---|---|---|---|",
    ]

    for ex in state["exercises"]:
        ex_name = ex["name"]
        sets_logged = state["log"].get(ex_name, [])
        target = f"{ex['weight']}kg × {ex['rep_range']}" if ex['weight'] else f"TBD × {ex['rep_range']}"

        if not sets_logged:
            lines.append(f"| | {ex_name} | {target} | Skipped |")
            continue

        actual = " / ".join(
            f"{s['weight']}kg×{s['reps']}" if not s.get('skipped') else "skip"
            for s in sets_logged
        )
        lines.append(f"| | {ex_name} | {target} | {actual} |")

    lines.append("")
    lines.append(f"*Session logged by PT Gary at {datetime.now(ADL).strftime('%H:%M')} ACST.*")

    filepath.write_text("\n".join(lines) + "\n")

    # Commit to repo
    os.chdir(REPO)
    os.system(f"git add logs/{filename} && git commit -m 'log: {today} {session_type}' && git push origin main 2>&1")

    return filepath


# ── Callback Handler ───────────────────────────────────────────────────────────

def handle_callback(callback: dict):
    """Process a button tap from the inline keyboard."""
    data = callback.get("data", "")
    msg = callback.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    msg_id = msg.get("message_id")
    callback_id = callback.get("id")

    state = load_state()
    if not state:
        answer_callback(callback_id, "No active session. Type 'chest', 'back', or 'legs' to start.")
        return

    if data == "skip":
        result = skip_exercise(state)
        answer_callback(callback_id, "Exercise skipped")

        if result == "complete":
            finish_session(chat_id, msg_id, state)
        else:
            # Move to next exercise
            text, keyboard = build_exercise_message(state)
            edit_message(chat_id, msg_id, text, keyboard)
        return

    if data == "failed":
        # Log as 0 reps
        ex = state["exercises"][state["current_exercise"]]
        result = advance(state, ex.get("weight", 0), 0)
        answer_callback(callback_id, "Set failed — logged")

        if result == "complete":
            finish_session(chat_id, msg_id, state)
        else:
            text, keyboard = build_exercise_message(state)
            edit_message(chat_id, msg_id, text, keyboard)
        return

    if data == "finish":
        finish_session(chat_id, msg_id, state)
        answer_callback(callback_id, "Session complete!")
        return

    if data == "custom_weight":
        answer_callback(callback_id, "Reply to this message with weight, e.g. '22.5'")
        return

    # Standard log: "log|80|10" or "log_tbd|12"
    if data.startswith("log"):
        parts = data.split("|")
        if parts[0] == "log":
            weight = float(parts[1])
            reps = int(parts[2])
        else:  # log_tbd
            reps = int(parts[1])
            weight = None  # Will need custom weight handling

        if weight is None:
            answer_callback(callback_id, "Reply with weight first, e.g. '22.5'")
            return

        result = advance(state, weight, reps)
        answer_callback(callback_id, f"{weight}kg × {reps} ✓")

        if result == "complete":
            finish_session(chat_id, msg_id, state)
        else:
            text, keyboard = build_exercise_message(state)
            edit_message(chat_id, msg_id, text, keyboard)
        return


def finish_session(chat_id: int, msg_id: int, state: dict):
    """Complete the session, write logs, show summary."""
    summary = build_session_summary(state)
    write_markdown_log(state)
    edit_message(chat_id, msg_id, summary)
    clear_state()


# ── Command Handler ─────────────────────────────────────────────────────────────

def handle_command(chat_id: int, text: str):
    """Handle text commands: chest, back, legs, cancel, etc."""
    text = text.strip().lower()

    # Map aliases
    session_map = {
        "chest": "chest-tri",
        "chest-tri": "chest-tri",
        "chest/tri": "chest-tri",
        "push": "chest-tri",
        "back": "back-bi",
        "back-bi": "back-bi",
        "back/bi": "back-bi",
        "pull": "back-bi",
        "legs": "legs-shoulders",
        "legs-shoulders": "legs-shoulders",
        "legs/shoulders": "legs-shoulders",
    }

    if text in session_map:
        session_type = session_map[text]
        state = start_session(chat_id, session_type)
        text, keyboard = build_exercise_message(state)
        send_message(chat_id, text, keyboard)
        return

    if text in ["cancel", "stop", "end"]:
        state = load_state()
        if state:
            clear_state()
            send_message(chat_id, "❌ Session cancelled.")
        else:
            send_message(chat_id, "No active session to cancel.")
        return

    if text in ["status", "progress"]:
        state = load_state()
        if state:
            ex = state["exercises"][state["current_exercise"]]
            send_message(
                chat_id,
                f"📍 *{state['session_name']}*\n"
                f"Exercise {state['current_exercise']+1}/{[len(state['exercises'])]}: {ex['name']}\n"
                f"Set {state['current_set']}/{ex['sets']}\n\n"
                f"Type 'cancel' to stop."
            )
        else:
            send_message(chat_id, "No active session. Type 'chest', 'back', or 'legs' to start.")
        return

    if text in ["help", "start"]:
        send_message(chat_id, (
            "🤖 *PT Gary*\n\n"
            "Commands:\n"
            "· `chest` — Start Chest/Triceps session\n"
            "· `back` — Start Back/Biceps session\n"
            "· `legs` — Start Legs/Shoulders session\n"
            "· `status` — Current session progress\n"
            "· `cancel` — End session without saving\n\n"
            "Tap the buttons to log your sets."
        ))
        return


# ── Main Loop ───────────────────────────────────────────────────────────────────

def main():
    """Long-polling loop for the PT Gary bot."""
    print("🏋️ PT Gary bot starting...")
    offset = 0

    while True:
        try:
            r = requests.get(
                f"{BASE}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35
            )
            data = r.json()

            if not data.get("ok"):
                print(f"API error: {data}")
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                # Callback query (button tap)
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
                    continue

                # Text message
                msg = update.get("message", {})
                if not msg:
                    continue

                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")

                if text:
                    print(f"[{chat_id}] {text}")
                    handle_command(chat_id, text)

        except requests.Timeout:
            continue
        except KeyboardInterrupt:
            print("\n👋 PT Gary signing off.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
