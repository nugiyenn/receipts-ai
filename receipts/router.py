"""ROUTER: deterministic lanes, blast radius and reading budget. No LLM is involved anywhere in this file."""
import re

import yaml

from . import config
from .ingest import hunk_for_line, ingest, load_areas, area_of
from .util import git, read_json, write_json

NOISE = {
    "this", "var", "new", "null", "true", "false", "return", "item", "items", "type", "name", "value", "values", "string",
    "int", "bool", "void", "base", "using", "static", "public", "private", "internal", "readonly", "class", "struct",
    "get", "set", "init", "out", "ref", "in", "is", "as", "if", "else", "foreach", "for", "while", "try", "catch",
    "continue", "break", "else", "param", "summary", "remarks", "returns", "see", "cref", "langword", "typeparam",
    "Task", "Fact", "Assert", "Equal", "Count", "Add", "Length", "Invoke", "Create", "Location", "Diagnostic",
}
DECL_RE = re.compile(r"\b(?:private|public|internal|protected|static)\b[^=;(){}]*?\b([A-Za-z_]\w*)\s*(?:\(|<[^>]*>\s*\()")
THIS_RE = re.compile(r"\bthis\.([A-Za-z_]\w*)")
CTX_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
IDENT_RE = re.compile(r"\b([A-Za-z_]\w*)\b")


def load_routing():
    return yaml.safe_load((config.POLICY / "routing.yaml").read_text(encoding="utf8"))


def lane_max(*lanes):
    return max(lanes, key=config.LANE_ORDER.index)


def changed_symbols(hunk):
    """Heuristic symbols a hunk touches: this.<member>, declared method names, and the enclosing member (hunk header)."""
    syms = {}
    for ln in hunk["text"].splitlines()[1:]:
        if not ln or ln[0] not in "+-":
            continue
        body = ln[1:]
        if ln[0] == "-":   # only members of EXISTING code that was modified/removed (new code has no callers yet)
            for m in THIS_RE.finditer(body):
                syms.setdefault(m.group(1), "member-access")
        m = DECL_RE.search(body)
        if m and ln[0] == "+":
            syms.setdefault(m.group(1), "declared")
    m = CTX_RE.search(hunk["ctx"] or "")
    if m:
        syms.setdefault(m.group(1), "enclosing")
    return {s: why for s, why in syms.items() if s not in NOISE and len(s) > 3}


def count_refs(symbol, head):
    out = git("grep", "-w", "-n", "--", symbol, head, "--", "src", check=False)
    lines = [l for l in out.splitlines() if l.strip()]
    return len(lines)


def blast_radius(change):
    """For each src/template hunk: referenced-by counts (git grep -w at head, src/ only). Returns per-hunk + max."""
    head = change["head"]
    cache, per_hunk = {}, {}
    for h in change["hunks"]:
        if h["kind"] not in ("src", "template"):
            continue
        res = []
        for sym, why in changed_symbols(h).items():
            if sym not in cache:
                cache[sym] = count_refs(sym, head)
            res.append({"symbol": sym, "why": why, "references": cache[sym]})
        res.sort(key=lambda r: -r["references"])
        per_hunk[h["id"]] = res
    allsyms = [r for v in per_hunk.values() for r in v]
    top = max(allsyms, key=lambda r: r["references"]) if allsyms else None
    return {"per_hunk": per_hunk, "max_references": top["references"] if top else 0,
            "top_symbol": top["symbol"] if top else None}


def _changed(h):
    return h["added"] + h["removed"]


def compute_flags(change, run, blast, thr):
    """Which hunks a human must read, and why. Conservative: unknown => flagged."""
    xray = read_json(run / "xray.json")
    refusals = (read_json(run / "refusals.json") or {}).get("refusals", [])
    claims = (read_json(run / "claims.json") or {}).get("claims", [])
    regen = read_json(run / "regen.json")
    cit = read_json(run / "citations.json")
    hunks = {h["id"]: h for h in change["hunks"]}
    why = {}

    def flag(hid, reason):
        if hid in hunks:
            why.setdefault(hid, []).append(reason)

    unprotected_by_xray, protected, structural = set(), set(), set()
    if xray:
        for g in xray.get("groups", []):
            for hid in g.get("hunks", []):
                res = g.get("result")
                (unprotected_by_xray if res == "unprotected" else protected if res == "load-bearing" else structural).add(hid)

    for h in change["hunks"]:
        k, hid = h["kind"], h["id"]
        if k in ("src", "template"):
            if not xray:
                flag(hid, "xray-pending: not yet shown to be protected by a test")
            elif hid in unprotected_by_xray:
                flag(hid, "unprotected: reverting this hunk breaks no test")
            elif hid in structural:
                flag(hid, "not-covered-by-xray: hunk could not be reverted in isolation (structural), not shown to be protected")
            elif hid not in protected:
                flag(hid, "not-covered-by-xray")
            top = max((r["references"] for r in blast["per_hunk"].get(hid, [])), default=0)
            if top >= thr:
                flag(hid, f"blast-radius: touches a symbol with {top} references (threshold {thr})")
        elif k == "generated":
            ok = False
            if regen:
                if regen.get("all_match") is True:
                    ok = True
                elif isinstance(regen.get("files"), dict):
                    ok = bool(regen["files"].get(h["path"]))
            if not ok:
                flag(hid, "regen-unverified: snapshot not proven by regeneration/pattern check")
        elif k == "template-output":
            twin = h["path"][:-3] + ".tt"
            ok = bool(regen and (regen.get("all_match") is True or (isinstance(regen.get("files"), dict) and regen["files"].get(h["path"]))))
            if not ok:
                flag(hid, f"regen-unverified: output of {twin} not proven by regeneration")
        # tests/docs: claims-level, not hunk reading, unless refused/claimed below

    for r in refusals:
        for hid in r.get("hunks", []) or []:
            flag(hid, f"refusal {r.get('id')} ({r.get('rule')})")
        for c in r.get("citations", []) or []:
            hid = hunk_for_line(change, c.get("path"), int(c.get("line", 0) or 0))
            if hid:
                flag(hid, f"refusal {r.get('id')} ({r.get('rule')})")
    invalid = set()
    if cit:
        invalid = {x["claim"] for x in cit.get("claims", []) if not x.get("all_valid", True)}
    for c in claims:
        lvl = c.get("evidence_level")
        weak = lvl in ("E1", "E0") or c.get("status") in ("unproven", "refuted", "refused") or c.get("id") in invalid
        if weak:
            for ct in c.get("citations", []) or []:
                hid = hunk_for_line(change, ct.get("path"), int(ct.get("line", 0) or 0))
                if hid:
                    flag(hid, f"claim {c.get('id')} has only {lvl or 'unknown'} evidence")
    return why, bool(xray), bool(regen)


def route(change_id: str, write=True):
    change_id = str(change_id)
    run = config.run_dir(change_id)
    change = ingest(change_id, write=write)
    routing = load_routing()
    thr = routing.get("blast_threshold", 10)
    _, areas = load_areas()
    amap = {a["name"]: a for a in areas}
    blast = blast_radius(change)
    why, have_xray, have_regen = compute_flags(change, run, blast, thr)
    hunks = {h["id"]: h for h in change["hunks"]}
    refusals = (read_json(run / "refusals.json") or {}).get("refusals", [])

    reasons, lane = [], "L0"
    kinds = {f["kind"] for f in change["files"]}
    only_snap = kinds <= {"generated", "template-output"}
    # default lane from areas, per file
    for f in change["files"]:
        lane = lane_max(lane, amap[f["area"]]["default_lane"] if f["kind"] not in ("generated", "template-output") else "L0")
    reasons.append({"rule": "areas", "lane": lane, "why": "highest default lane of the touched areas"})

    ceiling_areas = sorted({f["area"] for f in change["files"] if amap[f["area"]].get("ceiling")})
    if ceiling_areas:
        lane = lane_max(lane, "L3")
        reasons.append({"rule": "LR1", "lane": "L3", "why": f"touches ceiling area(s): {', '.join(ceiling_areas)}"})
    if any(r.get("rule", "")[:2] in ("R4", "R7") for r in refusals):
        lane = lane_max(lane, "L3")
        reasons.append({"rule": "LR2", "lane": "L3", "why": "refusal R4/R7 present"})
    if blast["max_references"] >= thr:
        lane = lane_max(lane, "L2")
        reasons.append({"rule": "LR3", "lane": "L2", "why": f"blast radius: {blast['top_symbol']} has {blast['max_references']} references (threshold {thr})"})
    unprot = [hid for hid, w in why.items() if any(x.startswith(("unprotected", "xray-pending", "not-covered")) for x in w)]
    if unprot and hunks[unprot[0]]["kind"] in ("src", "template"):
        lane = lane_max(lane, "L2")
        reasons.append({"rule": "LR4", "lane": "L2", "why": f"{len(unprot)} source hunk(s) " + ("unprotected by tests" if have_xray else "not yet proven protected (xray pending)")})
    if only_snap and not why:
        reasons.append({"rule": "LR5", "lane": "L0", "why": "only generated snapshots; all proven by regeneration"})
    elif not ceiling_areas and kinds <= {"test", "doc"} and not why:
        lane = lane_max("L1", "L0")
        reasons.append({"rule": "LR6", "lane": "L1", "why": "only tests/docs changed"})
    led_state = read_json(config.DATA / "ledger_state.json", {})
    led = led_state.get("areas", {}) if led_state.get("applies_to_routing") else {}   # synthetic history never affects real routing unless --apply
    for f in change["files"]:
        if led.get(f["area"], {}).get("lane") == "L3":
            lane = "L3"
            reasons.append({"rule": "LR7", "lane": "L3", "why": f"area {f['area']} demoted by trust ledger"})
            break
    if lane == "L3" and not any(r["rule"] in ("LR1", "LR2", "LR7") for r in reasons):
        pass

    # per-file lane
    flagged_files = {}
    for hid in why:
        flagged_files.setdefault(hunks[hid]["path"], []).append(hid)
    file_rows = []
    for f in change["files"]:
        fl = "L0" if f["kind"] in ("generated", "template-output") else amap[f["area"]]["default_lane"]
        if f["path"] in flagged_files:
            fl = lane_max(fl, "L2")
        if amap[f["area"]].get("ceiling") or lane == "L3":
            fl = "L3"
        file_rows.append({"path": f["path"], "area": f["area"], "kind": f["kind"], "lane": fl,
                          "changed_lines": f["added"] + f["removed"], "flagged_hunks": flagged_files.get(f["path"], [])})

    total = change["totals"]["changed_lines"]
    if lane == "L3":
        read_hunks = [h["id"] for h in change["hunks"]]
        budget = sum(_changed(h) for h in change["hunks"])
        basis = "L3: full read"
    else:
        read_hunks = sorted(why, key=lambda x: int(x[1:]))
        budget = sum(_changed(hunks[h]) for h in read_hunks)
        basis = "lines in flagged hunks"
    out = {
        "change": change_id, "lane": lane, "reasons": reasons,
        "areas": sorted({f["area"] for f in change["files"]}),
        "ceiling_areas": ceiling_areas,
        "blast_radius": {"threshold": thr, "max_references": blast["max_references"],
                         "top_symbol": blast["top_symbol"], "per_hunk": blast["per_hunk"]},
        "flagged_hunks": {h: why[h] for h in read_hunks if h in why},
        "reading_budget": {
            "lines": budget, "hunks": len(read_hunks), "total_changed_lines": total,
            "ratio": round(budget / total, 4) if total else 0.0, "basis": basis,
            "inputs": {"xray": have_xray, "regen": have_regen,
                       "refusals": bool(refusals),
                       "claims": (config.RUNS / change_id / "claims.json").exists()},
            "provisional": not have_xray,
        },
        "files": file_rows,
        "policy": {"areas": change["areas_version"], "routing": routing.get("version")},
    }
    if write:
        write_json(run / "route.json", out)
    return out
