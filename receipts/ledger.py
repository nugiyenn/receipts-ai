"""TRUST LEDGER: per-area track record + lane state machine (promote after clean streaks, demote on escapes / canary misses).
Synthetic history lives in data/ledger_history.json (labelled SYNTHETIC); real runs are appended separately and never mixed in."""
import yaml

from . import config
from .util import now_iso, read_json, write_json

LANES = config.LANE_ORDER
MIN_PLANTED_FOR_DEMOTION = 3
TRAILING_WEEKS = 4


def params():
    r = yaml.safe_load((config.POLICY / "routing.yaml").read_text(encoding="utf8"))
    return r["promotion"], r["demotion"], r.get("cold_start_lane", "L2")


def area_cfgs():
    a = yaml.safe_load((config.POLICY / "areas.yaml").read_text(encoding="utf8"))["areas"]
    return {x["name"]: x for x in a}


def new_state(area_cfg, cold):
    start = area_cfg.get("ceiling") or area_cfg["default_lane"]
    if area_cfg["default_lane"] in ("L0", "L1") and not area_cfg.get("ceiling"):
        start = area_cfg["default_lane"]
    elif not area_cfg.get("ceiling"):
        start = cold
    return {"lane": start, "clean": 0, "probation": False, "history": [], "events": []}


def step(state, week, rec, cfg, promo, demo):
    """Advance one week for one area. rec: receipts, escapes, canary_planted, canary_caught. Returns lane in effect DURING the week."""
    lane_during = state["lane"]
    ceiling = cfg.get("ceiling")
    floor_lane = cfg["default_lane"] if cfg["default_lane"] in ("L0", "L1") and not ceiling else None
    ev = []
    n, esc = rec["receipts"], rec["escapes"]
    if esc > 0:
        if not ceiling and state["lane"] != "L3":
            ev.append({"week": week, "type": "demotion", "reason": f"{esc} escape(s)", "from": state["lane"], "to": demo["on_escape"]})
        state.update(lane=demo["on_escape"] if not ceiling else ceiling, clean=max(0, n - esc), probation=True)
    else:
        state["clean"] += n
    planted, caught = rec["canary_planted"], rec["canary_caught"]
    week_recall = caught / planted if planted else None
    if week_recall is not None and planted >= MIN_PLANTED_FOR_DEMOTION and week_recall < demo["canary_recall_below"] and not ceiling:
        new = LANES[min(LANES.index(state["lane"]) + 1, 3)]
        if new != state["lane"]:
            ev.append({"week": week, "type": "demotion", "reason": f"canary recall {week_recall:.0%} < {demo['canary_recall_below']:.0%}", "from": state["lane"], "to": new})
            state.update(lane=new, clean=0, probation=(new == "L3"))
    state["history"].append({**rec, "week": week, "lane_during": lane_during})
    win = state["history"][-TRAILING_WEEKS:]
    wp, wc = sum(h["canary_planted"] for h in win), sum(h["canary_caught"] for h in win)
    trailing = wc / wp if wp else None
    if state["lane"] == "L3" and state["probation"] and not ceiling and state["clean"] >= demo["clean_to_leave_l3"]:
        ev.append({"week": week, "type": "recovery", "reason": f"{state['clean']} clean receipts after escape", "from": "L3", "to": "L2"})
        state.update(lane="L2", clean=0, probation=False)
    elif (not ceiling and state["lane"] == "L2" and state["clean"] >= promo["consecutive_clean"]
          and trailing is not None and trailing >= promo["min_canary_recall"]):
        ev.append({"week": week, "type": "promotion", "reason": f"{state['clean']} clean receipts, trailing canary recall {trailing:.0%}", "from": "L2", "to": "L1"})
        state.update(lane="L1", clean=0)
    if floor_lane and LANES.index(state["lane"]) < LANES.index(floor_lane):
        state["lane"] = floor_lane
    state["events"].extend(ev)
    state["history"][-1]["trailing_canary_recall"] = None if trailing is None else round(trailing, 3)
    state["history"][-1]["lane_after"] = state["lane"]
    return lane_during


def compute(history):
    promo, demo, cold = params()
    cfgs = area_cfgs()
    states = {}
    for area, weeks in history["areas"].items():
        st = new_state(cfgs[area], cold)
        for i, rec in enumerate(weeks):
            step(st, i + 1, rec, cfgs[area], promo, demo)
        states[area] = st
    return states


def _wavg(rows, key, wkey="receipts"):
    tot = sum(r[wkey] for r in rows)
    return sum(r[key] * r[wkey] for r in rows) / tot if tot else 0


def metrics(history, states):
    weeks = history["weeks"]
    glob = []
    for w in range(len(weeks)):
        rows = [states[a]["history"][w] for a in states]
        n = sum(r["receipts"] for r in rows)
        lines = sum(r["changed_lines"] for r in rows)
        glob.append({
            "week": w + 1, "start": weeks[w], "receipts": n,
            "median_review_min": round(_wavg(rows, "median_review_min"), 1),
            "median_time_to_merge_h": round(_wavg(rows, "median_ttm_h"), 1),
            "revert_rate": round(sum(r["reverts"] for r in rows) / n, 4) if n else 0,
            "escapes": sum(r["escapes"] for r in rows),
            "human_read_ratio": round(sum(r["routed_lines"] for r in rows) / lines, 4) if lines else 0,
            "routed_share_changes": round(sum(r["routed_changes"] for r in rows) / n, 4) if n else 0,
            "finding_precision": round(sum(r["findings_accepted"] for r in rows) / max(1, sum(r["findings"] for r in rows)), 3),
            "canary_recall": round(sum(r["canary_caught"] for r in rows) / max(1, sum(r["canary_planted"] for r in rows)), 3),
        })
    per_area = {}
    for a, st in states.items():
        h = st["history"]
        planted, caught = sum(x["canary_planted"] for x in h), sum(x["canary_caught"] for x in h)
        per_area[a] = {"lane": st["lane"], "clean_streak": st["clean"], "probation": st["probation"],
                       "receipts": sum(x["receipts"] for x in h), "escapes": sum(x["escapes"] for x in h),
                       "canary_recall": round(caught / planted, 3) if planted else None,
                       "events": st["events"]}
    return glob, per_area


FORMULAS = {
    "escape_rate": "post-merge defects attributed to L0/L1 changes ÷ L0/L1 changes",
    "finding_precision": "confirmed or owner-accepted AI findings ÷ all AI findings",
    "canary_recall": "canaries caught ÷ canaries planted (per area)",
    "routed_share": "changes (and lines) routed to L2/L3 ÷ all changes (lines)",
    "human_read_ratio": "reading-budget lines ÷ changed lines",
    "median_time_to_merge_h": "median hours from PR open to merge",
    "guardrail": "review minutes per PR must fall while revert rate and incidents stay flat",
}


def real_points():
    """Real runs from this hackathon (not synthetic): lane, budget, receipt status. Shown separately in the UI."""
    pts = []
    for d in sorted(config.RUNS.iterdir()) if config.RUNS.exists() else []:
        route = read_json(d / "route.json")
        if not route:
            continue
        rec = read_json(d / "receipt.json")
        pts.append({"change": route["change"], "lane": route["lane"], "reading_budget": route["reading_budget"],
                    "receipt_signed": bool(rec), "owner": rec["owner"] if rec else None,
                    "canary_recall": (read_json(config.DATA / "drill.json") or {}).get("overall", {}).get("recall_union")})
    return pts


def build(write=True, applies_to_routing=False):
    hist = read_json(config.DATA / "ledger_history.json")
    if hist is None:
        raise SystemExit("data/ledger_history.json missing — run: python scripts/gen_ledger.py")
    states = compute(hist)
    glob, per_area = metrics(hist, states)
    out = {
        "synthetic": True,
        "label": "SYNTHETIC: seeded simulation of 12 weeks, generated by scripts/gen_ledger.py; not measurements of any real team.",
        "seed": hist.get("seed"), "generated_at": now_iso(),
        "applies_to_routing": applies_to_routing,
        "weeks": hist["weeks"], "formulas": FORMULAS,
        "baseline_human_only_review_min": hist.get("baseline_human_only_review_min"), "baseline_note": hist.get("baseline_note"),
        "rules": {"promotion": params()[0], "demotion": params()[1], "cold_start_lane": params()[2],
                  "ceiling_areas_never_promote": True},
        "areas": per_area, "global": glob,
        "area_weekly": {a: [{k: h[k] for k in ("week", "receipts", "escapes", "canary_planted", "canary_caught", "lane_during", "lane_after", "trailing_canary_recall", "median_review_min")} for h in st["history"]] for a, st in states.items()},
        "real_runs": real_points(),
        "real_runs_label": "REAL: produced by this submission's pipeline on the provided sample changes.",
    }
    if write:
        write_json(config.DATA / "ledger_state.json", out)
    return out


def print_summary(out):
    print(out["label"])
    print(f"{'wk':>3} {'recpts':>6} {'rev-min':>7} {'ttm-h':>6} {'revert%':>7} {'read%':>6} {'canary':>6}")
    for g in out["global"]:
        print(f"{g['week']:>3} {g['receipts']:>6} {g['median_review_min']:>7} {g['median_time_to_merge_h']:>6} {g['revert_rate']*100:>7.1f} {g['human_read_ratio']*100:>6.1f} {g['canary_recall']*100:>5.0f}%")
    for a, v in out["areas"].items():
        print(f"  {a:22} lane={v['lane']} streak={v['clean_streak']} escapes={v['escapes']} recall={v['canary_recall']}")
        for e in v["events"]:
            print(f"      wk{e['week']}: {e['type']} {e['from']}→{e['to']} ({e['reason']})")
