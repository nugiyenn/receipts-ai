"""CANARY DRILL: plant known defects in the AI's change and measure whether the reviewer caught them.
Inputs (owned by whoever runs the pipeline per canary):
  canaries/canaries.yaml   list of {id, type, area, change, description, patch, expect_rule?}
  canaries/<patch>         unified diff applied on top of the change's HEAD
  runs/drill/<id>/signals.json   {"caught": bool, "by": ["xray","refusal:R2","citation","test-fail", ...], "note": "..."}   (authoritative)
     or, if absent: runs/drill/<id>/{findings,refusals,xray}.json are matched by location against the planted lines.
Output: data/drill.json with recall overall / per type / per area, the missed canaries, and the ledger consequence (computed, not applied)."""
import shutil
import subprocess

import yaml

from . import config
from .ingest import parse_diff
from .ledger import area_cfgs, params, LANES
from .util import git, now_iso, read_json, write_json

DRILL = config.RUNS / "drill"


def load_canaries():
    p = config.CANARIES / "canaries.yaml"
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf8"))
    return data["canaries"] if isinstance(data, dict) else data


def planted_ranges(canary):
    """New-side line ranges touched by the canary patch (relative to head + patch)."""
    patch = (config.CANARIES / canary["patch"]).read_text(encoding="utf8")
    out = []
    for f in parse_diff(patch):
        for h in f["hunks"]:
            out.append({"path": f["b"], "start": h["new_start"], "end": h["new_start"] + max(h["new_len"], 1) - 1})
    return out


def plant(change_id, canary_id, worktree_root=None):
    """Create a detached git worktree at the change's head with the canary applied; return its path.
    Local only: nothing is committed. Remove with unplant()."""
    can = next(c for c in load_canaries() if c["id"] == canary_id)
    root = (worktree_root or (config.ROOT.parent / "wt")) 
    root.mkdir(parents=True, exist_ok=True)
    wt = root / f"canary-{change_id}-{canary_id}"
    head = git("rev-parse", config.BRANCHES[str(change_id)]).strip()
    if wt.exists():
        unplant(change_id, canary_id, worktree_root)
    git("worktree", "add", "--detach", str(wt), head)
    r = subprocess.run(["git", "apply", "--whitespace=nowarn", str((config.CANARIES / can["patch"]).resolve())], cwd=str(wt), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"canary {canary_id} does not apply: {r.stderr.strip()[:400]}")
    d = DRILL / canary_id
    d.mkdir(parents=True, exist_ok=True)
    diff = git("diff", "--no-color", "-U3", head, cwd=wt)
    (d / "change_patched.diff").write_text(diff, encoding="utf8")
    return wt


def unplant(change_id, canary_id, worktree_root=None):
    wt = (worktree_root or (config.ROOT.parent / "wt")) / f"canary-{change_id}-{canary_id}"
    git("worktree", "remove", "--force", str(wt), check=False)
    shutil.rmtree(wt, ignore_errors=True)


def _near(path, line, ranges, slack=3):
    return any(path == r["path"] and r["start"] - slack <= line <= r["end"] + slack for r in ranges)


def judge(canary):
    d = DRILL / canary["id"]
    sig = read_json(d / "signals.json")
    if sig is not None:
        return {"status": "caught" if sig.get("caught") else "missed", "by": sig.get("by", []), "note": sig.get("note")}
    if not d.exists():
        return {"status": "not-run", "by": [], "note": "no drill output yet"}
    ranges = planted_ranges(canary)
    by = []
    for f in (read_json(d / "findings.json") or {}).get("findings", []):
        if _near(f.get("path"), int(f.get("line", 0) or 0), ranges):
            by.append(f"finding:{f.get('kind', '?')}")
    for r in (read_json(d / "refusals.json") or {}).get("refusals", []):
        for c in r.get("citations", []) or []:
            if _near(c.get("path"), int(c.get("line", 0) or 0), ranges):
                by.append(f"refusal:{r.get('rule')}")
    ch = read_json(d / "change.json")
    xr = read_json(d / "xray.json")
    if ch and xr:
        hunks = {h["id"]: h for h in ch["hunks"]}
        for g in xr.get("groups", []):
            if g.get("result") == "unprotected":
                for hid in g.get("hunks", []):
                    h = hunks.get(hid)
                    if h and _near(h["path"], h["new_start"], ranges, slack=h["new_len"]):
                        by.append("xray:unprotected")
    return {"status": "caught" if by else "missed", "by": sorted(set(by)), "note": None}


def score(write=True):
    cans = load_canaries()
    rows, by_type, by_area = [], {}, {}
    for c in cans:
        j = judge(c)
        rows.append({"id": c["id"], "type": c.get("type"), "area": c.get("area"), "description": c.get("description"), **j})
    ran = [r for r in rows if r["status"] in ("caught", "missed")]
    for r in ran:
        for key, bucket in ((r["type"], by_type), (r["area"], by_area)):
            b = bucket.setdefault(key, {"planted": 0, "caught": 0})
            b["planted"] += 1
            b["caught"] += r["status"] == "caught"
    for bucket in (by_type, by_area):
        for b in bucket.values():
            b["recall"] = round(b["caught"] / b["planted"], 3)
    n, k = len(ran), sum(r["status"] == "caught" for r in ran)
    promo, demo, cold = params()
    cfgs = area_cfgs()
    effect = {}
    for a, b in by_area.items():
        cfg = cfgs.get(a)
        if not cfg:
            continue
        before = cold if (cfg["default_lane"] in ("L2",) and not cfg.get("ceiling")) else (cfg.get("ceiling") or cfg["default_lane"])
        after = before
        if b["planted"] >= 3 and b["recall"] < demo["canary_recall_below"] and not cfg.get("ceiling"):
            after = LANES[min(LANES.index(before) + 1, 3)]
        effect[a] = {"lane_before": before, "lane_after": after, "recall": b["recall"], "planted": b["planted"],
                     "reason": None if before == after else f"canary recall {b['recall']:.0%} < {demo['canary_recall_below']:.0%}"}
    # --- per-signal-family recall (read from signals.json written by evidence/canary_runner.py) ---
    fam_names = ["tests", "deterministic-rules", "gemini", "claude"]
    fam = {f: {"caught": [], "missed": []} for f in fam_names}
    sigs = {r["id"]: read_json(DRILL / r["id"] / "signals.json") for r in ran}
    for cid, sg in sigs.items():
        for f in fam_names:
            ok = bool(((sg or {}).get("by_family") or {}).get(f))
            (fam[f]["caught"] if ok else fam[f]["missed"]).append(cid)
    per_family = {f: {"caught": len(v["caught"]), "planted": len(ran), "recall": round(len(v["caught"]) / len(ran), 3) if ran else None, **v}
                  for f, v in fam.items() if any((sg or {}).get("by_family") for sg in sigs.values())}
    only_one = {}
    for cid, sg in sigs.items():
        on = [f for f in fam_names if ((sg or {}).get("by_family") or {}).get(f)]
        if len(on) == 1:
            only_one[cid] = on[0]
    llm_free = [cid for cid, sg in sigs.items() if ((sg or {}).get("by_family") or {}).get("tests") or ((sg or {}).get("by_family") or {}).get("deterministic-rules")]
    routed = [cid for cid, sg in sigs.items() if ((sg or {}).get("xray_routed_to_human_NOT_counted") or {}).get("routed")]
    extra = {}
    if per_family:
        extra = {
            "per_family": per_family,
            "caught_by_exactly_one_family": only_one,
            "recall_without_any_llm": {"caught": len(llm_free), "planted": len(ran), "recall": round(len(llm_free) / len(ran), 3) if ran else None,
                                       "missed": [c for c in sigs if c not in llm_free],
                                       "what_if_note": "If no LLM reviewer were available, the always-on part (tests + deterministic rules) would score this recall; below the ledger's demotion threshold means the area could not be trusted with lighter review."},
            "per_canary_signals": {cid: {"fired": [f for f in fam_names if ((sg or {}).get("by_family") or {}).get(f)],
                                         "caught_by_one_family_only": cid in only_one} for cid, sg in sigs.items()},
            "rounds": {"round_1": [c["id"] for c in cans if c["id"] in {f"C{i}" for i in range(1, 9)}],
                       "round_2_harder_added_after_round_1_results": [c["id"] for c in cans if c["id"] in {"C9", "C10", "C11"}]},
            "caveats": ["Round-1 deterministic detectors (R2/R4/R6/assertion drop) were written by the same author who wrote the canaries, so their hits on C4, C5, C7, C8 are not blind. The R2 rule was also fixed after seeing the C8 result (documented).",
                        "The fresh Claude reviewer is the same model family as the one that produced claims.json, so its hits are less independent than Gemini's.",
                        "11 canaries we wrote ourselves; one run per reviewer; matching = path + line proximity + hidden keywords."],
            "hunk_level_xray_routing": {"routed_to_human": routed, "recall": round(len(routed) / len(ran), 3) if ran else None,
                                        "note": "Hunk-level X-Ray cannot see a planted change inside a hunk that is load-bearing for another reason. Recorded separately; NOT counted as caught."},
        }
    out = {"generated_at": now_iso(), "label": "REAL drill results (canaries planted by us, so recall on our canaries ≠ recall on real defects)",
           "overall": {"planted": n, "caught": k, "recall_union": round(k / n, 3) if n else None, "not_run": len(rows) - n},
           "by_type": by_type, "by_area": by_area, "missed": [r["id"] for r in ran if r["status"] == "missed"],
           "canaries": rows, "ledger_effect": effect, **extra}
    if per_family:
        best_f, best_v = max(per_family.items(), key=lambda kv: len(kv[1]["caught"]))
        ov = out["overall"]
        out["overall"] = {"planted": ov["planted"], "caught": ov["caught"],
                          "recall_union": ov["recall_union"],
                          "recall_best_single": {"reviewer": best_f, "caught": len(best_v["caught"]), "planted": best_v["planted"], "recall": round(len(best_v["caught"]) / best_v["planted"], 3)},
                          "recall_no_llm": {"caught": extra["recall_without_any_llm"]["caught"], "planted": extra["recall_without_any_llm"]["planted"],
                                            "recall": extra["recall_without_any_llm"]["recall"]},
                          "not_run": ov["not_run"],
                          "note": "recall_union counts a canary as caught when any signal fires. 6 of 11 rest on one signal, so read recall_best_single and recall_no_llm next to it."}
    prev = read_json(config.DATA / "drill.json", {}) or {}
    if "held_out" in prev and "held_out" not in out:
        out["held_out"] = prev["held_out"]       # separate round, written by canaries/heldout; keep it on rebuild
    if write:
        write_json(config.DATA / "drill.json", out)
    return out
