#!/usr/bin/env python3
"""
PT Gary — Voice Processor
Downloads Telegram voice messages, transcribes with faster-whisper, parses workout data.

Usage:
  python3 voice_processor.py <file_id>
  → Returns JSON: {"text": "nine reps", "reps": 9, "weight": null, "command": null}
"""

import json
import os
import re
import sys
import tempfile
import subprocess
from pathlib import Path
from faster_whisper import WhisperModel

# ── Config ────────────────────────────────────────────────────────────────────
import re as _re
with open('/tmp/tg_send.py') as f:
    _m = _re.search(r'BOT_TOKEN = "([^"]+)"', f.read())
    BOT_TOKEN = _m.group(1)

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
CACHE = Path("/Users/gary/.hermes/audio_cache")
CACHE.mkdir(parents=True, exist_ok=True)

# Lazy-load whisper model (tiny for speed, sufficient for numbers/short commands)
_model = None


def get_model():
    global _model
    if _model is None:
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model


# ── Download ───────────────────────────────────────────────────────────────────

def download_voice(file_id: str) -> Path:
    """Download a Telegram voice message .ogg file. Returns local path."""
    import requests

    # Get file path from Telegram
    r = requests.get(f"{BASE}/getFile", params={"file_id": file_id})
    data = r.json()
    if not data.get("ok"):
        raise Exception(f"getFile failed: {data}")

    file_path = data["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    # Download
    local = CACHE / f"voice_{file_id}.ogg"
    r = requests.get(url)
    local.write_bytes(r.content)
    return local


# ── Convert ────────────────────────────────────────────────────────────────────

def convert_to_wav(ogg_path: Path) -> Path:
    """Convert .ogg to 16kHz mono WAV for whisper."""
    wav_path = ogg_path.with_suffix(".wav")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(ogg_path),
        "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        str(wav_path)
    ], capture_output=True)
    return wav_path


# ── Transcribe ─────────────────────────────────────────────────────────────────

def transcribe(wav_path: Path) -> str:
    """Transcribe WAV to text using faster-whisper."""
    model = get_model()
    segments, _ = model.transcribe(str(wav_path), beam_size=5, language="en")
    text = " ".join(s.text for s in segments).strip().lower()
    return text


# ── Parse ──────────────────────────────────────────────────────────────────────

# Number words → digits
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
}

# Commands that can appear in voice
COMMANDS = {
    "chest": "chest-tri",
    "back": "back-bi",
    "legs": "legs-shoulders",
    "start": "start",
    "cancel": "cancel",
    "stop": "cancel",
    "end": "cancel",
    "skip": "skip",
    "status": "status",
    "finish": "finish",
    "done": "finish",
}

FAIL_WORDS = {"fail", "failed", "failure", "couldn't", "could not", "missed", "no rep", "zero"}


def parse_transcription(text: str) -> dict:
    """Parse transcribed text into structured workout data.

    Returns:
        {
            "raw": "nine reps",
            "reps": 9,
            "weight": null,
            "command": null,
            "is_failure": false,
        }
    """
    result = {
        "raw": text,
        "reps": None,
        "weight": None,
        "command": None,
        "is_failure": False,
    }

    text = text.strip().lower()

    # Check for commands first
    for cmd_word, cmd in COMMANDS.items():
        if cmd_word in text.split():
            result["command"] = cmd
            return result

    # Check for failure
    if any(fw in text for fw in FAIL_WORDS):
        result["is_failure"] = True
        result["reps"] = 0
        return result

    # Try to extract number words
    words = text.split()
    for word in words:
        if word in NUMBER_WORDS:
            result["reps"] = NUMBER_WORDS[word]
            return result

    # Try to extract digits: "9", "9 reps", "10 at 80"
    digits = re.findall(r'\b(\d+)\b', text)
    if digits:
        # First digit is almost always reps in the context of "how many reps"
        result["reps"] = int(digits[0])

        # Second digit (if present) might be weight
        if len(digits) >= 2:
            result["weight"] = int(digits[1])

    return result


# ── Main ───────────────────────────────────────────────────────────────────────

def process_voice(file_id: str) -> dict:
    """Full pipeline: download → convert → transcribe → parse."""
    ogg = download_voice(file_id)
    wav = convert_to_wav(ogg)
    text = transcribe(wav)

    # Cleanup temp files
    ogg.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)

    result = parse_transcription(text)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 voice_processor.py <file_id>")
        sys.exit(1)

    result = process_voice(sys.argv[1])
    print(json.dumps(result, indent=2))
