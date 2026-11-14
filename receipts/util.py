import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path


def git(*args, cwd=None, check=True, text=True):
    from . import config
    r = subprocess.run(["git", *args], cwd=str(cwd or config.REPO), capture_output=True, text=text, errors="replace" if text else None)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:500]}")
    return r.stdout


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf8"))


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf8")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def glob_to_regex(glob: str) -> re.Pattern:
    """Translate a ** glob (gitignore-ish) to a regex that matches the full path."""
    i, out = 0, ""
    while i < len(glob):
        c = glob[i]
        if c == "*":
            if glob[i:i + 3] == "**/":
                out += "(?:.*/)?"
                i += 3
                continue
            if glob[i:i + 2] == "**":
                out += ".*"
                i += 2
                continue
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        else:
            out += re.escape(c)
        i += 1
    return re.compile("^" + out + "$")


def append_log(path, heading, body):
    """Append-only timestamped entry for DECISIONS.md / LESSONS.md."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf8") as f:
        f.write(f"\n### {now_iso()} — {heading}\n{body.strip()}\n")
