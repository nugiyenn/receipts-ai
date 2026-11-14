"""Held-out round entry point. Reuses receipts/evidence/canary_runner.py UNCHANGED (detectors, prompts, test filter,
matching rule); it only redirects where manifests, patches, outputs and worktrees live.
Usage (from receipts/):  python3 canaries/heldout/run_heldout.py detectors|tests|reviews|assemble [ids...]"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from receipts import config, drill
from receipts.evidence import canary_runner as cr
from receipts.util import now_iso, read_json, write_json

HO_C = config.ROOT / "canaries" / "heldout"
HO_D = config.RUNS / "drill" / "heldout"
config.CANARIES = HO_C          # drill.load_canaries / planted_ranges / plant and cr.detectors read this at call time
drill.DRILL = HO_D
cr.DRILL = HO_D

_plant, _unplant = drill.plant, drill.unplant
def _root(r): return config.ROOT.parent / "wt" / ("ho-" + (r.name if r else "test"))
drill.plant = lambda ch, cid, root=None: _plant(ch, cid, _root(root))
drill.unplant = lambda ch, cid, root=None: _unplant(ch, cid, _root(root))

def ids_of(args): return [c["id"] for c in cr.sel(args)]

def assemble(args):
    rows = []
    for c in cr.sel(args):
        d = HO_D / c["id"]
        det = read_json(d / "detectors.json") or {"fired": [], "signals": {}}
        tests = read_json(d / "tests.json") or {"outcome": "not-run"}
        ranges = drill.planted_ranges(c)
        gj = (read_json(d / "gemini_review.json") or {}).get("findings")
        cj = (read_json(d / "claude_findings.json") or {}).get("findings")
        gem = cr.judge_reviewer(gj, ranges, c["detect_keywords"])
        cla = cr.judge_reviewer(cj, ranges, c["detect_keywords"])
        by = []
        if tests.get("outcome") == "red": by.append("test-fail")
        for k in det["fired"]:
            sg = det["signals"][k]
            if any(sg["path"] == r["path"] for r in ranges):
                by.append({"R4": "refusal:R4", "R2": "refusal:R2", "R6": "refusal:R6", "assertion_drop": "assertion-drop"}[k])
        if gem["caught"]: by.append("llm:gemini")
        if cla["caught"]: by.append("llm:claude")
        fam = {"tests": "test-fail" in by,
               "deterministic-rules": bool(set(by) - {"test-fail", "llm:gemini", "llm:claude"}),
               "gemini": gem["caught"], "claude": cla["caught"]}
        loc = {"gemini": bool(gem.get("hits") or gem.get("near_but_off_target")),
               "claude": bool(cla.get("hits") or cla.get("near_but_off_target"))}
        loc["any"] = loc["gemini"] or loc["claude"] or fam["tests"] or fam["deterministic-rules"]
        sig = {"canary": c["id"], "type": c["type"], "authored_by": c.get("authored_by"), "caught": bool(by), "by": by,
               "by_family": fam, "location_only_secondary": loc, "note": c["description"], "tests": tests,
               "detectors": det["fired"], "gemini": gem, "claude": cla,
               "xray_routed_to_human_NOT_counted": cr.xray_routing(c, tests),
               "evidence_refs": [f"runs/drill/heldout/{c['id']}/{n}" for n in ("tests.json", "tests.log", "detectors.json", "gemini_review.json", "claude_findings.json", "review_input.diff")]}
        write_json(d / "signals.json", sig)
        rows.append(sig)
        print(c["id"], "CAUGHT" if by else "MISSED", by, "| location-only:", loc)
    fams = ["tests", "deterministic-rules", "gemini", "claude"]
    n = len(rows)
    per = {f: {"caught": [r["canary"] for r in rows if r["by_family"][f]]} for f in fams}
    for f in fams:
        per[f].update(planted=n, recall=round(len(per[f]["caught"]) / n, 3) if n else None,
                      missed=[r["canary"] for r in rows if not r["by_family"][f]])
    one = {}
    for r in rows:
        on = [f for f in fams if r["by_family"][f]]
        if len(on) == 1: one[r["canary"]] = on[0]
    no_llm = [r["canary"] for r in rows if r["by_family"]["tests"] or r["by_family"]["deterministic-rules"]]
    caught = [r["canary"] for r in rows if r["caught"]]
    best = max(fams, key=lambda f: len(per[f]["caught"]))
    loc_any = [r["canary"] for r in rows if r["location_only_secondary"]["any"]]
    block = {
        "generated_at": now_iso(),
        "label": "HELD-OUT round: 6 bugs authored by Gemini, not by us. Detectors, prompts, filter and matching rule frozen before authoring (runs/drill/heldout/PREREGISTRATION.json).",
        "planted": n, "caught_by_union": len(caught), "recall_union": round(len(caught) / n, 3) if n else None,
        "recall_best_single": {"reviewer": best, "caught": len(per[best]["caught"]), "planted": n, "recall": per[best]["recall"]},
        "recall_no_llm": {"caught": len(no_llm), "planted": n, "recall": round(len(no_llm) / n, 3) if n else None, "missed": [r["canary"] for r in rows if r["canary"] not in no_llm]},
        "per_family": per, "caught_by_exactly_one_family": one,
        "missed": [r["canary"] for r in rows if not r["caught"]],
        "location_only_secondary": {"any_signal_near_planted_hunk": len(loc_any), "planted": n,
                                    "gemini": sum(r["location_only_secondary"]["gemini"] for r in rows),
                                    "claude": sum(r["location_only_secondary"]["claude"] for r in rows),
                                    "note": "Finding within +-2 lines of the planted hunk, keywords ignored. Secondary metric, fixed before results."},
        "per_canary": {r["canary"]: {"type": r["type"], "description": r["note"], "by": r["by"], "caught": r["caught"],
                                     "fired_families": [f for f in fams if r["by_family"][f]], "tests_outcome": r["tests"].get("outcome")} for r in rows},
        "caveats": ["All 6 bugs were authored by one model (Gemini 3.1 Pro), one authoring call, n=6. Small sample, no confidence interval worth quoting.",
                    "Gemini is both the author and one of the four reviewers (separate fresh call, no authoring context), so its result is correlated with the authoring.",
                    "The fresh Claude reviewer is the same model family that wrote claims.json.",
                    "detect_keywords were written by the author. A finding must be near the planted hunk AND contain a keyword; the location-only metric is reported next to it.",
                    "The deterministic rules (R2, R4, R6, assertion drop) were written by us earlier and were not changed in this round.",
                    "Three of the six bugs sit in test files, which says something about what the author model thinks an agent breaks. Reviewer noise on the unplanted head is in runs/drill/BASELINE.",
                    "One run per reviewer; LLM output varies between runs."]}
    write_json(config.DATA / "drill_heldout.json", block)
    dj = read_json(config.DATA / "drill.json")
    dj["held_out"] = block
    write_json(config.DATA / "drill.json", dj)
    print(json.dumps({k: block[k] for k in ("planted", "caught_by_union", "recall_union", "recall_best_single", "recall_no_llm", "missed", "caught_by_exactly_one_family")}, indent=1))

if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    ids = ids_of(args)
    if cmd == "detectors": cr.run_detectors(ids)
    elif cmd == "tests": cr.run_tests(ids)
    elif cmd == "reviews":
        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(3) as ex:
            for r in ex.map(cr.review_one, ids): print("review", r)
    elif cmd == "assemble": assemble(args)
