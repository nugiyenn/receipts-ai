"""LLM adapter: Gemini (independent model family) with a content-hash cache.

Reads GEMINI_API_KEY from the environment or from ../.env.local (never printed,
never written to runs/). Every call is cached under runs/_llm_cache/<sha>.json so the
demo replays offline. Cache entries record model, prompt sha256 and timestamp.
Only public OSS diffs and our own claims are sent; no personal data.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # receipts/
CACHE = ROOT / "runs" / "_llm_cache"
DEFAULT_MODEL = "gemini-3.1-pro-preview"


def _key() -> str:
    k = os.environ.get("GEMINI_API_KEY")
    if k:
        return k
    for p in (ROOT.parent / ".env.local", ROOT / ".env.local"):
        if p.is_file():
            for line in p.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"\'')
    raise RuntimeError("GEMINI_API_KEY not found (env or .env.local)")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def generate(system: str, user: str, *, model: str = DEFAULT_MODEL, json_mode: bool = True,
             live: bool = True, temperature: float = 0.0) -> dict:
    """Return {'text','model','prompt_sha256','cached','ts'}. Replays from cache first."""
    prompt_sha = sha256(model + "\n" + system + "\n" + user)
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{prompt_sha}.json"
    if f.is_file():
        d = json.loads(f.read_text())
        d["cached"] = True
        return d
    if not live:
        raise RuntimeError("cache miss in replay mode")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature,
                             **({"responseMimeType": "application/json"} if json_mode else {})},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": _key()},
    )
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                resp = json.load(r)
            break
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:300]}"
            if e.code in (429, 500, 503):
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(last)
    else:
        raise RuntimeError(last)
    text = "".join(p.get("text", "") for p in resp["candidates"][0]["content"]["parts"])
    out = {"text": text, "model": model, "prompt_sha256": prompt_sha,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "usage": resp.get("usageMetadata", {})}
    f.write_text(json.dumps(out, indent=1))
    out["cached"] = False
    return out
