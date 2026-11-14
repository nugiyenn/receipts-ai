"""Baseline: what does a plain 'review this PR' prompt find?

Two naive reviewers, one run each, identical prompt, no hints about our findings:
  gemini  llm.py, model gemini-3.1-pro-preview
  claude  fresh `claude -p` session, no tools, empty working directory (same invocation as the canary drill)

Usage (from receipts/):
  python3 -m receipts.baseline run [--change ID ...]    run and cache the 8 reviews
  python3 -m receipts.baseline report                   merge runs/baseline/judgments.json into data/baseline.json

Everything is cached under runs/baseline/<id>/. Judgments (did a naive review mention a ground-truth
finding) are written by hand into runs/baseline/judgments.json after reading the outputs; this script only
checks that every ground-truth finding has a judgment for every reviewer and computes the totals.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import llm

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
BASE = RUNS / "baseline"
REPO = ROOT.parent / "repo"
CHANGES = ["2283", "2234", "2297", "2129"]
GEMINI_MODEL = "gemini-3.1-pro-preview"
CLAUDE_MODEL = "claude-sonnet-5-5"

PROMPT = ("You are reviewing a pull request. Requirement: {req}\n\nDiff:\n{diff}\n\n"
          "List any bugs, risks or concerns, and say whether you would approve it.")


def issue_text(cid: str) -> str:
    """Title and body of the GitHub issue, from the saved issue page (the API is rate limited)."""
    page = RUNS / cid / "issue_page.html"
    if not page.exists():
        page = BASE / f"issue_page_{cid}.html"
    s = page.read_text(errors="ignore")
    dec = json.JSONDecoder()
    body = None
    for m in re.finditer(r'"body":', s):
        try:
            body, _ = dec.raw_decode(s[m.end():])
            break
        except ValueError:
            continue
    title = re.search(r"^title:\s*(.+)$", (ROOT / "requirements" / f"REQ-{cid}.yaml").read_text(), re.M).group(1).strip()
    if body is None:
        raise RuntimeError(f"no issue body found for {cid}")
    return f"{title}\n\n{body.strip()}"


def build_prompt(cid: str) -> str:
    ch = json.loads((RUNS / cid / "change.json").read_text())
    diff = subprocess.run(["git", "-C", str(REPO), "diff", ch["base"], ch["head"]],
                          capture_output=True, text=True, check=True).stdout
    return PROMPT.format(req=issue_text(cid), diff=diff)


def run_gemini(prompt: str, out: Path) -> dict:
    if out.exists():
        return json.loads(out.read_text())
    t = time.time()
    r = llm.generate("", prompt, model=GEMINI_MODEL, json_mode=False)
    res = {"reviewer": "gemini", "model": GEMINI_MODEL, "prompt_sha256": llm.sha256(prompt),
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seconds": round(time.time() - t, 1),
           "text": r["text"], "usage": r.get("usage", {})}
    out.write_text(json.dumps(res, indent=1))
    return res


def run_claude(prompt: str, out: Path) -> dict:
    if out.exists():
        return json.loads(out.read_text())
    scratch = BASE / "_claude_cwd"
    scratch.mkdir(parents=True, exist_ok=True)
    t = time.time()
    p = subprocess.run(["claude", "-p", "--model", CLAUDE_MODEL, "--tools", "", "--no-session-persistence"],
                       input=prompt, cwd=scratch, capture_output=True, text=True, timeout=1500)
    res = {"reviewer": "claude", "model": CLAUDE_MODEL,
           "produced_by": "fresh `claude -p` session, no tools, empty working directory, no conversation context",
           "prompt_sha256": llm.sha256(prompt), "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "seconds": round(time.time() - t, 1), "text": p.stdout, "returncode": p.returncode,
           "stderr": p.stderr[-300:]}
    out.write_text(json.dumps(res, indent=1))
    return res


def run_one(cid: str, who: str):
    d = BASE / cid
    d.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(cid)
    (d / "prompt.txt").write_text(prompt)
    fn = run_gemini if who == "gemini" else run_claude
    r = fn(prompt, d / f"{who}.json")
    print(f"{cid} {who}: {len(r['text'])} chars, {r.get('seconds')}s", flush=True)
    return r


def cmd_run(ids):
    jobs = [(c, w) for c in ids for w in ("gemini", "claude")]
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(lambda a: run_one(*a), jobs))


def cmd_report():
    j = json.loads((BASE / "judgments.json").read_text())
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "prompt_template": PROMPT,
           "reviewers": {"gemini": GEMINI_MODEL, "claude": f"{CLAUDE_MODEL} via claude -p, no tools"},
           "limits": j["limits"], "changes": {}, "totals": {}}
    tot = {w: {"gt": 0, "yes": 0, "partly": 0, "no": 0, "false_claims": 0, "unverified_claims": 0,
               "approve": 0, "request_changes": 0}
           for w in ("gemini", "claude")}
    silent_approve = {"gemini": 0, "claude": 0}
    for cid in CHANGES:
        cj = j["changes"][cid]
        row = {"ground_truth": cj["ground_truth"], "has_confirmed_silent_failure": cj["has_confirmed_silent_failure"],
               "reviewers": {}}
        for w in ("gemini", "claude"):
            rv = cj["reviewers"][w]
            raw = json.loads((BASE / cid / f"{w}.json").read_text())
            missing = [g["id"] for g in cj["ground_truth"] if g["id"] not in rv["matches"]]
            if missing:
                sys.exit(f"{cid}/{w}: no judgment for {missing}")
            counts = {"yes": 0, "partly": 0, "no": 0}
            for g in cj["ground_truth"]:
                counts[rv["matches"][g["id"]]["match"]] += 1
            row["reviewers"][w] = {"verdict": rv["verdict"], "confidence_words": rv["confidence_words"],
                                   "output_chars": len(raw["text"]), "seconds": raw.get("seconds"),
                                   "ground_truth_counts": counts, "matches": rv["matches"],
                                   "naive_findings": rv["naive_findings"],
                                   "false_or_unverifiable": rv["false_or_unverifiable"],
                                   "found_that_receipts_missed": rv.get("found_that_receipts_missed", []),
                                   "output_ref": f"runs/baseline/{cid}/{w}.json"}
            t = tot[w]
            t["gt"] += len(cj["ground_truth"])
            for k in counts:
                t[k] += counts[k]
            t["false_claims"] += sum(1 for x in rv["false_or_unverifiable"] if x["status"] == "false")
            t["unverified_claims"] += sum(1 for x in rv["false_or_unverifiable"] if x["status"] == "unverified")
            t["approve" if rv["verdict"] == "approve" else "request_changes"] += 1
            if cj["has_confirmed_silent_failure"] and rv["verdict"] == "approve":
                silent_approve[w] += 1
        out["changes"][cid] = row
    out["totals"] = {"per_reviewer": tot, "approvals_on_changes_with_confirmed_silent_failure": silent_approve,
                     "changes_with_confirmed_silent_failure": [c for c in CHANGES if j["changes"][c]["has_confirmed_silent_failure"]]}
    out["what_naive_review_lacks"] = j["what_naive_review_lacks"]
    (ROOT / "data" / "baseline.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out["totals"], indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="receipts.baseline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--change", nargs="*", default=CHANGES)
    sub.add_parser("report")
    a = ap.parse_args(argv)
    cmd_run(a.change) if a.cmd == "run" else cmd_report()


if __name__ == "__main__":
    main()
