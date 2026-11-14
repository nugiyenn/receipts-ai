#!/usr/bin/env python3
"""Gemini text-to-speech helper with a content-hash cache (docs/media/tts_cache/, git-ignored).

The API key is read from GEMINI_API_KEY or /Users/.../Junction2/.env.local, as receipts/llm.py does. It is never
printed and never written to the cache. Only the narration text, which is public project content, is sent.
Output: 24 kHz, 16-bit, mono PCM wrapped as a WAV file.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
import wave

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "docs" / "media" / "tts_cache"
MODEL = "gemini-2.5-flash-preview-tts"
STYLE = "Say calmly and clearly, like an engineer presenting to colleagues, at a natural unhurried pace"


def _key() -> str:
    k = os.environ.get("GEMINI_API_KEY")
    if k:
        return k
    for p in (ROOT.parent / ".env.local", ROOT / ".env.local"):
        if p.is_file():
            for line in p.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("GEMINI_API_KEY not found (env or .env.local)")


def synth(text: str, voice: str = "Kore", model: str = MODEL, style: str = STYLE) -> pathlib.Path:
    """Return the path to a cached WAV for this text, voice, model and style."""
    CACHE.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(f"{model}|{voice}|{style}|{text}".encode()).hexdigest()[:24]
    out = CACHE / f"{voice}-{h}.wav"
    if out.is_file():
        return out
    body = {
        "contents": [{"parts": [{"text": f"{style}: {text}"}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": _key()},
    )
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                resp = json.load(r)
            part = resp["candidates"][0]["content"]["parts"][0]["inlineData"]
            pcm = base64.b64decode(part["data"])
            break
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:200]}"
            if e.code in (429, 500, 503):
                time.sleep(8 * (attempt + 1))
                continue
            raise RuntimeError(last)
        except (KeyError, IndexError) as e:
            last = f"unexpected response shape: {e}"
            time.sleep(4)
    else:
        raise RuntimeError(last)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    return out


def duration(path: pathlib.Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


if __name__ == "__main__":
    import sys
    p = synth(" ".join(sys.argv[2:]) or "Test.", sys.argv[1] if len(sys.argv) > 1 else "Kore")
    print(p.name, round(duration(p), 2), "s")
