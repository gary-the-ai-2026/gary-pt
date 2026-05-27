#!/usr/bin/env python3
"""
PT Gary — Coaching Voice Prompts
Generates TTS audio for each stage of a workout session.

Design: JARVIS tone — calm, direct, dry wit where appropriate.
Never cheerleader. Never aggressive. Competent and present.
"""

COACHING = {
    # ── Session Start ──────────────────────────────────────────────────────
    "session_start": lambda name, count: (
        f"{name} day. {count} exercises ahead. "
        f"Take your time with each set. I'll guide you through."
    ),

    # ── Exercise Intro ─────────────────────────────────────────────────────
    "exercise_intro": lambda num, total, name, sets, rep_range, weight, rest: (
        f"Exercise {num} of {total}. {name}. "
        f"{sets} sets, {rep_range} reps. "
        f"{'Working weight is ' + weight + '.' if weight else 'Find a weight that challenges you within the rep range.'} "
        f"Rest {rest} between sets. Set one, when you're ready."
    ),

    # ── Set Prompts ────────────────────────────────────────────────────────
    "set_prompt": lambda set_num, total_sets, weight, rep_target: (
        f"Set {set_num} of {total_sets}. "
        f"{weight + ' on the bar. ' if weight else ''}"
        f"Aim for {rep_target} reps."
    ),

    "last_set": lambda set_num, weight, rep_target: (
        f"Final set. Set {set_num}. "
        f"{weight + '. ' if weight else ''}"
        f"Give me everything you've got. {rep_target} reps is the target."
    ),

    # ── Set Feedback ───────────────────────────────────────────────────────
    "set_complete_hit": lambda reps, target: (
        f"{reps} reps. Right on target. Rest and we go again."
    ),

    "set_complete_exceed": lambda reps, target: (
        f"{reps} reps. That's above target. Strong work."
    ),

    "set_complete_under": lambda reps, target: (
        f"{reps} reps. Slightly under target. No issue — we'll adjust."
    ),

    "set_complete_failure": lambda: (
        f"Failed the set. That happens. Rest up and we'll match it on the next one."
    ),

    "rest_prompt": lambda rest_time, next_set: (
        f"Rest {rest_time}. Set {next_set} coming up."
    ),

    # ── Exercise Complete ──────────────────────────────────────────────────
    "exercise_complete": lambda name, sets_data: (
        f"{name} complete. Moving on."
    ),

    "exercise_complete_all_hit": lambda name: (
        f"{name} done. All sets on target. Weight increases next session."
    ),

    # ── Session Complete ───────────────────────────────────────────────────
    "session_complete": lambda summary_brief: (
        f"Session complete. {summary_brief} "
        f"Log updated and dashboard refreshed. Good work. I'll be here when you're ready for the next one."
    ),

    # ── Status / Misc ──────────────────────────────────────────────────────
    "paused": lambda: (
        f"Session paused. Say 'resume' when you're ready to continue."
    ),

    "error": lambda: (
        f"I didn't catch that. Say the number of reps, or 'failed' if you missed the set."
    ),

    "no_session": lambda: (
        f"No active session. Say 'chest', 'back', or 'legs' to start one."
    ),
}
