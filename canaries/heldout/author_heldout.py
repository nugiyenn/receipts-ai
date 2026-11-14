"""Ask Gemini to author held-out canaries for #2283, then turn its exact edits into unified diffs against head.
Gemini sees only the PR diff and the head source of the changed files. It is NOT shown our detectors, our canaries,
our claims, or what catches what."""
import json, subprocess, sys, re, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from receipts import llm, config

REPO = config.ROOT.parent / "repo"
HEAD = "origin/ju26-issue-2283"
BASE = HEAD + "~1"
OUT = config.ROOT / "canaries" / "heldout"
RAW = config.ROOT / "runs" / "drill" / "heldout"

def show(path, rev=HEAD):
    return subprocess.run(["git", "show", f"{rev}:{path}"], cwd=REPO, capture_output=True, text=True, check=True).stdout

def diff():
    return subprocess.run(["git", "diff", "--no-color", "-U3", BASE, HEAD], cwd=REPO, capture_output=True, text=True, check=True).stdout

SYSTEM = """You are helping evaluate an automated code reviewer. Write realistic, SUBTLE bugs that an AI coding agent could plausibly introduce on top of the pull request below. The bugs will be planted one at a time on top of the current head, and a reviewer will then be asked to find them.
Rules:
- Produce exactly 6 independent bugs. Vary the type across: logic inversion, off-by-one or wrong variable, missed null case, over-broad filter, false documentation claim, weakened test assertion, silent exception swallow. Use 6 different types.
- Each bug must be a small, minimal edit that compiles (C# / .NET 8). Make bugs that the existing tests in tests/MessagePack.SourceGenerator.Tests are unlikely to catch, and that look like a normal agent mistake, not a comment saying 'bug'.
- Do not touch more than one file per bug. Do not add comments that reveal the bug.
- Express each edit as exact text replacement: 'old' must be copied character-for-character from the provided file and must appear EXACTLY ONCE in that file (include enough surrounding lines to be unique); 'new' is its replacement. Keep indentation exactly.
- Also give 'detect_keywords': 3 to 6 lowercase words or short phrases that a correct review finding describing your bug would plausibly contain.
Output ONLY JSON: {"bugs":[{"id":"H1","type":"...","description":"one sentence of what the bug is","path":"repo-relative path","old":"...","new":"...","detect_keywords":["..."]}]}"""

def build_user(extra=""):
    files = ["src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs", "doc/analyzers/MsgPack004.md",
             "tests/MessagePack.SourceGenerator.Tests/GenericsFormatterTests.cs"]
    parts = ["PULL REQUEST DIFF (base..head):\n" + diff()]
    for f in files:
        parts.append(f"\n===== FILE {f} (head) =====\n" + show(f))
    return "\n".join(parts) + extra

def parse(text):
    return json.loads(re.search(r"\{.*\}", text, re.S).group(0))["bugs"]

def validate(bugs):
    ok, bad = [], []
    cache = {}
    for b in bugs:
        try:
            src = cache.setdefault(b["path"], show(b["path"]))
            n = src.count(b["old"])
            if n != 1: raise ValueError(f"'old' occurs {n} times in {b['path']}")
            if b["old"] == b["new"]: raise ValueError("no-op edit")
            ok.append(b)
        except Exception as e:
            bad.append({"id": b.get("id"), "why": str(e)})
    return ok, bad

if __name__ == "__main__":
    user = build_user()
    g = llm.generate(SYSTEM, user, model="gemini-3.1-pro-preview", temperature=0.4)
    (RAW / "author_prompt_system.txt").write_text(SYSTEM)
    (RAW / "author_prompt_user_sha256.txt").write_text(llm.sha256(user))
    (RAW / "author_raw_round1.json").write_text(json.dumps({"model": g["model"], "prompt_sha256": g["prompt_sha256"], "ts": g["ts"], "text": g["text"]}, indent=1))
    bugs = parse(g["text"])
    ok, bad = validate(bugs)
    print("round1 bugs:", len(bugs), "valid:", [b["id"] for b in ok], "bad:", bad)
    json.dump({"bugs": bugs, "valid": [b["id"] for b in ok], "bad": bad}, open(RAW / "author_round1_parsed.json", "w"), indent=1)
