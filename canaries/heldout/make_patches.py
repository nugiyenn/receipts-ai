import json, subprocess, sys, shutil, yaml
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from receipts import config
from receipts.ingest import area_of, load_areas
REPO = config.ROOT.parent / "repo"; HEAD = "origin/ju26-issue-2283"
OUT = config.ROOT / "canaries" / "heldout"; RAW = config.ROOT / "runs" / "drill" / "heldout"
WT = config.ROOT.parent / "wt" / "ho-author"
bugs = json.load(open(RAW / "author_round1_parsed.json"))["bugs"]
if len(sys.argv) > 1: bugs = json.load(open(sys.argv[1]))["bugs"]
subprocess.run(["git", "worktree", "remove", "--force", str(WT)], cwd=REPO, capture_output=True)
shutil.rmtree(WT, ignore_errors=True); WT.parent.mkdir(exist_ok=True)
head = subprocess.run(["git", "rev-parse", HEAD], cwd=REPO, capture_output=True, text=True).stdout.strip()
subprocess.run(["git", "worktree", "add", "--detach", str(WT), head], cwd=REPO, check=True, capture_output=True)
_, areas = load_areas(); cans = []
try:
    for b in bugs:
        f = WT / b["path"]; orig = f.read_text(encoding="utf8")
        assert orig.count(b["old"]) == 1, b["id"]
        f.write_text(orig.replace(b["old"], b["new"]), encoding="utf8")
        patch = subprocess.run(["git", "diff", "--no-color", "-U3"], cwd=WT, capture_output=True, text=True).stdout
        f.write_text(orig, encoding="utf8")
        (OUT / f"{b['id']}.patch").write_text(patch, encoding="utf8")
        cans.append({"id": b["id"], "type": b["type"], "area": area_of(b["path"], areas)["name"], "change": "2283",
                     "patch": f"{b['id']}.patch", "description": b["description"], "authored_by": "gemini-3.1-pro-preview",
                     "detect_keywords": b["detect_keywords"]})
finally:
    subprocess.run(["git", "worktree", "remove", "--force", str(WT)], cwd=REPO, capture_output=True); shutil.rmtree(WT, ignore_errors=True)
header = "# HELD-OUT canaries for #2283, authored by Gemini (not by us). detect_keywords were written by the author before any result.\n"
(OUT / "canaries.yaml").write_text(header + yaml.safe_dump({"canaries": cans}, sort_keys=False, allow_unicode=True))
print([c["id"] for c in cans])
