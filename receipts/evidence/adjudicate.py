"""Adjudicator: deterministic evidence levels for claims.

The LLM proposes claims (runs/<id>/claims.llm.json, never modified). THIS module decides, from
run artifacts only, each claim's `evidence_level` and `status`. No model call, no confidence number.

Evidence levels
  E3  Executed. The claim's verifier is `timemachine` and tests resolved from the claim's citations
      fail on base and pass on head (runs/<id>/timemachine.json).
  E2  Mechanical. Either X-Ray shows every cited source hunk is load-bearing (reverting it turns a test
      red; runs/<id>/xray.json) or a deterministic check passed (regen.json pattern/real-regeneration
      check for `regen` claims; template pair check for `static` claims).
      Deviation from spec 5.4a, which called load-bearing E3: a load-bearing hunk proves the hunk is
      *protected by a test*, not that the claim about its behaviour is true. E3 is reserved for an
      executed demonstration of the claim's own behaviour.
  E1  Argued. All citations validate (runs/<id>/citations.json) but nothing executed supports the claim,
      or the executed evidence shows the tests do not reproduce the bug (tests-prove-nothing flag).
  E0  No evidence: a citation is invalid (wrong line, hallucinated quote) or the claim has no citations.

Status
  proven     E3 and nothing contradicts it.
  supported  E2 and nothing contradicts it.
  unproven   E1 or E0, or E3/E2 with an unresolved contradiction note.
  refuted    a hypothesis whose outcome is CONFIRMED contradicts the claim (HYPOTHESIS_LINKS, 'refute'),
             or regen.json shows the claim's cited snapshot deviating from the claim.
  refused    a refusal in refusals.json references the claim and the claim is not E3-by-timemachine,
             or every cited source hunk is `unprotected` by X-Ray (no covering test).
             An E3 claim that a refusal also references keeps `proven` and gets `partially_refused`:
             the refusal is about a different question (e.g. root cause), which the owner still decides.

Precedence: refuted > refused > (level based status).

HYPOTHESIS_LINKS is a small human-reviewed policy table (like policy/*.yaml): it says which claim a
hypothesis speaks to. Outcome strings are normalised: CONFIRMED -> refute/qualify as listed,
PARTIALLY CONFIRMED -> qualify only, REJECTED/inconclusive -> no effect.

Outputs: runs/<id>/claims.json (levels/status/evidence_refs written in), runs/<id>/adjudication.json
(per-claim audit trail, requirement coverage, tests-prove-nothing flags).
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config
from ..util import git, now_iso, read_json, write_json

VERSION = "adjudicator-1"

# change -> hypothesis id -> {claims, effect}. Effects: refute | qualify.
HYPOTHESIS_LINKS = {
    "2283": {"H1": {"claims": ["C4"], "effect": "qualify",
                    "note": "H1 shows MsgPack004 dropped for a metadata type; the claim is about source-declared types, so it is qualified, not refuted."}},
    "2234": {"H4": {"claims": ["C4"], "effect": "refute",
                    "note": "Root-cause commit 1a74a620 is not in this branch; the diff patches a different crash."},
             "H5": {"claims": ["C6"], "effect": "qualify",
                    "note": "Generator-only builds emit the formatter without reporting the skipped member."}},
    "2297": {},
}

_METHOD = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:public|private|internal|protected)\s+(?:static\s+)?(?:async\s+)?[\w<>\[\],\.\?\s]+?\s+(\w+)\s*\(")


def _norm_outcome(s: str) -> str:
    s = (s or "").strip().lower()
    if s.startswith("partially"):
        return "partial"
    if s.startswith("confirmed"):
        return "confirmed"
    return "other"


def _head_lines(repo_head, path, cache):
    key = (repo_head, path)
    if key not in cache:
        try:
            cache[key] = git("show", f"{repo_head}:{path}").splitlines()
        except Exception:
            cache[key] = None
    return cache[key]


def _methods(lines):
    """[(start_line_1based, name)] for method declarations."""
    out = []
    for i, t in enumerate(lines, 1):
        m = _METHOD.match(t)
        if m and not t.strip().startswith("//"):
            out.append((i, m.group(1)))
    return out


def _enclosing(methods, line):
    cur = None
    for start, name in methods:
        if start <= line:
            cur = name
        else:
            break
    return cur


def _body(lines, methods, name):
    for idx, (start, n) in enumerate(methods):
        if n == name:
            end = methods[idx + 1][0] - 1 if idx + 1 < len(methods) else len(lines)
            return "\n".join(lines[start - 1:end])
    return ""


def hunk_result(xray, hid):
    """('load-bearing'|'unprotected'|'structural'|None, group id, how). Prefer the hunk's own group;
    a structural hunk falls back to the smallest multi-hunk group that contains it."""
    if not xray:
        return None, None, None
    groups = xray.get("groups", [])
    single = [g for g in groups if g.get("hunks") == [hid]]
    if single and single[0].get("result") in ("load-bearing", "unprotected"):
        return single[0]["result"], single[0]["id"], "alone"
    multi = sorted((g for g in groups if hid in g.get("hunks", []) and len(g["hunks"]) > 1), key=lambda g: len(g["hunks"]))
    if multi and multi[0].get("result") in ("load-bearing", "unprotected"):
        return multi[0]["result"], multi[0]["id"], "jointly"
    if single:
        return single[0].get("result"), single[0]["id"], "alone"
    return None, None, None


def _timemachine_rule(claim, cits, tm, change, cache):
    """Resolve tests from cited test-file lines, then compare base/head."""
    if not tm:
        return None
    names = {t["name"].split(".")[-1]: t for t in tm.get("tests", [])}
    resolved, via = {}, []
    for c in cits:
        path = c["path"]
        if "/tests/" not in "/" + path:
            continue
        lines = _head_lines(change["head"], path, cache)
        if not lines:
            continue
        ms = _methods(lines)
        m = _enclosing(ms, int(c["line"]))
        if m in names:
            resolved[m] = names[m]
            via.append(f"{path}:{c['line']} is inside test {m}")
        elif m:
            for tn in names:
                if m in _body(lines, ms, tn):
                    resolved[tn] = names[tn]
                    via.append(f"{path}:{c['line']} is in helper {m}, called by test {tn}")
    if not resolved:
        return {"matched": False, "via": via}
    genuine = [n for n, t in resolved.items() if t["base"] == "fail" and t["head"] == "pass"]
    passes_on_base = [n for n, t in resolved.items() if t["base"] == "pass"]
    return {"matched": True, "via": via, "genuine": genuine, "pass_on_base": passes_on_base,
            "tests": sorted(resolved)}


def _template_pair_check(change, paths):
    """Static mechanical check: the attribute literal count in each .tt equals the count in its .cs at head."""
    rows = []
    for p in paths:
        if not p.endswith(".tt"):
            continue
        cs = p[:-3] + ".cs"
        a = _head_lines(change["head"], p, {}) or []
        b = _head_lines(change["head"], cs, {}) or []
        na = sum(t.count("ExcludeFromCodeCoverage") for t in a)
        nb = sum(t.count("ExcludeFromCodeCoverage") for t in b)
        rows.append({"tt": p, "cs": cs, "tt_count": na, "cs_count": nb, "ok": na > 0 and na == nb})
    return rows


def ensure_regen_files(change_id, change, regen):
    """Derive regen['files'] ({path: bool}) so the router can clear generated hunks. Additive and recorded."""
    if not regen or isinstance(regen.get("files"), dict):
        return regen
    bad = {x["path"] for x in regen.get("generated_nonmatching", [])}
    files = {}
    for f in change["files"]:
        if f["kind"] == "generated":
            files[f["path"]] = f["path"] not in bad
        elif f["kind"] == "template-output":
            files[f["path"]] = all(r["ok"] for r in _template_pair_check(change, [f["path"][:-3] + ".tt"])) and bool(_template_pair_check(change, [f["path"][:-3] + ".tt"]))
    regen["files"] = files
    regen["files_derived_by"] = f"{VERSION}: generated -> matches strict attribute pattern; template-output -> .tt/.cs attribute literal counts equal at head"
    write_json(config.run_dir(change_id) / "regen.json", regen)
    return regen


def _req_items(change_id):
    import yaml
    p = config.REQS / f"REQ-{change_id}.yaml"
    if not p.exists():
        return []
    d = yaml.safe_load(p.read_text()) or {}
    out = []
    for sec in ("functional", "non_functional", "security"):
        for it in d.get(sec, []) or []:
            out.append({"id": it["id"], "section": sec, "text": it.get("text", "")})
    return out


def adjudicate(change_id: str, write=True):
    from .. import citations
    cid = str(change_id)
    run = config.run_dir(cid)
    backup = run / "claims.llm.json"
    cj = run / "claims.json"
    if not backup.exists():
        backup.write_text(cj.read_text(encoding="utf8"), encoding="utf8")     # keep the LLM's original untouched
    doc = read_json(backup)
    change = read_json(run / "change.json")
    tm = read_json(run / "timemachine.json")
    xray = read_json(run / "xray.json")
    regen = read_json(run / "regen.json")
    refusals = (read_json(run / "refusals.json") or {}).get("refusals", [])
    hyps = {h["id"]: h for h in (read_json(run / "hypotheses.json") or {}).get("hypotheses", [])}
    regen = ensure_regen_files(cid, change, regen)

    # citations in claims.json are identical to claims.llm.json (adjudication never edits them)
    cit = citations.validate(cid, write=write)
    cit_by = {r["claim"]: r for r in cit.get("claims", [])}

    hunks = {h["id"]: h for h in change["hunks"]}
    ref_by_claim = {}
    for r in refusals:
        for c in r.get("claims", []) or []:
            ref_by_claim.setdefault(c, []).append(r["id"])
    linked = {}
    for hid, link in HYPOTHESIS_LINKS.get(cid, {}).items():
        h = hyps.get(hid)
        if not h:
            continue
        oc = _norm_outcome(h.get("outcome"))
        for c in link["claims"]:
            if (link["effect"] == "refute" and oc == "confirmed") or (link["effect"] == "qualify" and oc in ("confirmed", "partial")):
                linked.setdefault(c, []).append({"hypothesis": hid, "effect": link["effect"] if oc == "confirmed" else "qualify", "note": link["note"]})
    nonmatching = {x["path"] for x in (regen or {}).get("generated_nonmatching", [])}

    audit, cache = [], {}
    for cl in doc["claims"]:
        a = {"claim": cl["id"], "verifier": cl.get("verifier"), "rules": [], "refs": [], "flags": []}
        cits = (cit_by.get(cl["id"]) or {}).get("citations", [])
        valid = bool(cits) and all(c.get("valid") for c in cits)
        level, status = "E1", "unproven"
        if not valid:
            level = "E0"
            a["rules"].append("E0: " + ("no citations" if not cits else "invalid citation(s): " + "; ".join(c["reason"] for c in cits if not c.get("valid"))))
        else:
            v = cl.get("verifier")
            src_hunks = sorted({c["hunk"] for c in cits if c.get("hunk") and hunks.get(c["hunk"], {}).get("kind") in ("src", "template")})
            if v == "timemachine":
                r = _timemachine_rule(cl, cits, tm, change, cache)
                if r and r["matched"]:
                    a["timemachine"] = r
                    if r["genuine"]:
                        level = "E3"
                        a["rules"].append(f"E3: {len(r['genuine'])} test(s) fail on base and pass on head: {', '.join(r['genuine'])}")
                        a["refs"] += [f"runs/{cid}/timemachine.json#{n}" for n in r["genuine"]]
                        if r["pass_on_base"]:
                            a["flags"].append(f"tests-prove-nothing: {len(r['pass_on_base'])} cited test(s) also pass on base")
                    else:
                        a["rules"].append("E1: every cited test already passes on base, so the tests do not reproduce the bug (tests-prove-nothing)")
                        a["flags"].append("tests-prove-nothing: " + ", ".join(r["pass_on_base"]))
                        a["refs"] += [f"runs/{cid}/timemachine.json#{n}" for n in r["pass_on_base"]]
                else:
                    a["rules"].append("E1: no test cited by this claim appears in timemachine.json, so nothing was executed for it")
            elif v == "xray":
                res = {h: hunk_result(xray, h) for h in src_hunks}
                if not src_hunks:
                    a["rules"].append("E1: claim cites no source hunk (docs/tests only), so X-Ray has nothing to say")
                elif not xray:
                    a["rules"].append("E1: X-Ray not run for this change")
                else:
                    lb = [h for h, r in res.items() if r[0] == "load-bearing"]
                    up = [h for h, r in res.items() if r[0] == "unprotected"]
                    a["xray"] = {h: {"result": r[0], "group": r[1], "how": r[2]} for h, r in res.items()}
                    a["refs"] += [f"runs/{cid}/xray.json#{r[1]}" for r in res.values() if r[1]]
                    if up:
                        a["flags"].append("unprotected hunk(s): " + ", ".join(up))
                    if up and not lb:
                        level, a["xray_all_unprotected"] = "E1", True
                        a["rules"].append(f"E1: every cited source hunk is unprotected by tests ({', '.join(up)})")
                    elif up:
                        a["rules"].append(f"E1: cited hunk(s) {', '.join(up)} unprotected, so the claim cannot be fully backed (load-bearing: {', '.join(lb)})")
                    elif lb and len(lb) == len(src_hunks):
                        level = "E2"
                        a["rules"].append(f"E2: all cited source hunks are load-bearing ({', '.join(lb)}); protected by a test, not an executed demonstration of the claim")
                    else:
                        a["rules"].append("E1: cited hunk(s) could not be isolated by X-Ray")
            elif v == "regen":
                bad = sorted({c["path"] for c in cits if c["path"] in nonmatching})
                txt = cl.get("text", "")
                if bad:
                    level, a["regen_deviation"] = "E2", bad
                    a["rules"].append("E2: regen.json check shows the cited snapshot(s) deviate from the claim: " + ", ".join(Path(b).name for b in bad))
                    a["refs"].append(f"runs/{cid}/regen.json#generated_nonmatching")
                elif re.search(r"untouched|not consumed", txt):
                    a["rules"].append("E1: claim concerns files outside the diff; regen verifies only changed files")
                elif regen and regen.get("generated_matching") is not None:
                    level = "E2"
                    a["rules"].append(f"E2: {regen['generated_matching']} of {regen['generated_total']} snapshots match the strict attribute pattern; the claim's cited files are among them")
                    a["refs"].append(f"runs/{cid}/regen.json")
                else:
                    a["rules"].append("E1: regen.json missing")
            elif v == "static":
                tt = _template_pair_check(change, [c["path"] for c in cits])
                if tt:
                    a["template_pairs"] = tt
                    if all(r["ok"] for r in tt):
                        level = "E2"
                        a["rules"].append(f"E2: {len(tt)} .tt/.cs pair(s) carry the same attribute literal count at head")
                        a["refs"].append(f"runs/{cid}/adjudication.json#{cl['id']}")
                    else:
                        a["rules"].append("E1: template pair check failed or inconclusive")
                else:
                    a["rules"].append("E1: static claim, citations validate, no deterministic check implemented for it")
            else:
                a["rules"].append(f"E1: verifier '{v}' has no executed evidence (argued; citations validate)")
        # status
        status = {"E3": "proven", "E2": "supported"}.get(level, "unproven")
        lk = linked.get(cl["id"], [])
        if any(x["effect"] == "refute" for x in lk):
            status = "refuted"
            a["rules"].append("refuted: " + "; ".join(f"{x['hypothesis']} confirmed: {x['note']}" for x in lk if x["effect"] == "refute"))
            a["refs"] += [f"runs/{cid}/hypotheses.json#{x['hypothesis']}" for x in lk]
        elif a.get("regen_deviation") and cl.get("verifier") == "regen":
            status = "refuted"
            a["rules"].append("refuted: the cited snapshot(s) contain changes the claim says do not exist")
        else:
            refs = ref_by_claim.get(cl["id"], [])
            tm_e3 = level == "E3" and cl.get("verifier") == "timemachine"
            if refs and not tm_e3:
                status = "refused"
                a["rules"].append(f"refused: referenced by refusal(s) {', '.join(refs)}")
            elif a.get("xray_all_unprotected"):
                status = "refused"
                a["rules"].append("refused: every cited source hunk is unprotected, no test covers it")
            elif refs:
                a["partially_refused"] = refs
                a["rules"].append(f"proven, partially refused: refusal(s) {', '.join(refs)} cover a different question the owner decides")
            if lk and status not in ("refuted", "refused"):
                a["qualified_by"] = lk
                a["flags"].append("qualified: " + "; ".join(x["hypothesis"] for x in lk))
            for x in lk:
                a["refs"].append(f"runs/{cid}/hypotheses.json#{x['hypothesis']}")
        a["level"], a["status"] = level, status
        audit.append(a)
        cl["evidence_level"], cl["status"] = level, status
        cl["evidence_refs"] = sorted(set(a["refs"]))
        cl["adjudication"] = {"rule": a["rules"][0] if a["rules"] else "", "flags": a["flags"]}
        if a.get("partially_refused"):
            cl["adjudication"]["partially_refused"] = a["partially_refused"]

    # requirement coverage
    best = {}
    order = {"E3": 3, "E2": 2, "E1": 1, "E0": 0}
    for cl in doc["claims"]:
        r = cl.get("requirement")
        if r:
            best.setdefault(r, []).append((order[cl["evidence_level"]], cl["id"], cl["status"]))
    cov = []
    for it in _req_items(cid):
        rows = best.get(it["id"], [])
        top = max((x[0] for x in rows), default=None)
        cov.append({**it, "claims": [x[1] for x in rows],
                    "best_level": None if top is None else "E%d" % top,
                    "coverage": "uncovered" if top is None else "weak" if top <= 1 else "evidenced"})
    prove_nothing = []
    for t in (tm or {}).get("tests", []):
        if t.get("base") == "pass":
            prove_nothing.append(t["name"])
    tm_summary = None
    if tm:
        tm_summary = {"tests": len(tm.get("tests", [])), "pass_on_base": len(prove_nothing), "genuine_fail_to_pass": sum(1 for t in tm["tests"] if t["base"] == "fail" and t["head"] == "pass"),
                      "tests_that_prove_nothing": prove_nothing}
    counts = {}
    for a in audit:
        counts[a["level"]] = counts.get(a["level"], 0) + 1
    status_counts = {}
    for a in audit:
        status_counts[a["status"]] = status_counts.get(a["status"], 0) + 1
    doc.update({"adjudicated_at": now_iso(), "adjudicator": VERSION,
                "adjudication_note": "evidence_level and status are set by receipts/evidence/adjudicate.py from runs/ artifacts; the LLM-written original is runs/%s/claims.llm.json" % cid})
    out = {"change": cid, "adjudicator": VERSION, "adjudicated_at": now_iso(), "levels": counts, "statuses": status_counts,
           "timemachine": tm_summary, "requirement_coverage": cov,
           "uncovered_requirements": [c["id"] for c in cov if c["coverage"] == "uncovered"],
           "claims": audit}
    if write:
        write_json(cj, doc)
        write_json(run / "adjudication.json", out)
    return out


def line_level_budget(change_id: str, window: int = 4, write=True):
    """Reading budget at line granularity, computed after `router.route` has written route.json.

    The router flags whole hunks. For src/template/generated hunks that is right: a human reads the hunk.
    For doc/test hunks it over-counts: a 190-line test hunk is flagged because a weak or refused claim cites
    8 lines of it. Here a flagged doc/test hunk counts only the lines within +-`window` of lines that weak,
    refused, refuted or refusal-cited claims cite. Everything else is unchanged. Written to adjudication.json
    as `reading_budget_line_level` next to the router's hunk-level `reading_budget` (route.json), never replacing it.
    """
    cid = str(change_id)
    run = config.run_dir(cid)
    change = read_json(run / "change.json")
    route = read_json(run / "route.json")
    claims = (read_json(run / "claims.json") or {}).get("claims", [])
    refusals = (read_json(run / "refusals.json") or {}).get("refusals", [])
    adj = read_json(run / "adjudication.json") or {}
    if not (change and route):
        return None
    hunks = {h["id"]: h for h in change["hunks"]}
    flagged = route.get("flagged_hunks", {})
    cited = []                                   # (path, line) the owner is asked to look at
    for c in claims:
        if c.get("evidence_level") in ("E0", "E1") or c.get("status") in ("unproven", "refused", "refuted"):
            cited += [(x["path"], int(x["line"])) for x in c.get("citations", [])]
    for r in refusals:
        cited += [(x["path"], int(x["line"])) for x in r.get("citations", []) or []]
    lines, rows = 0, []
    for hid in sorted(flagged, key=lambda s: int(s[1:])):
        h = hunks[hid]
        full = h["added"] + h["removed"]
        if h["kind"] in ("doc", "test"):
            span = set()
            for p, ln in cited:
                if p == h["path"] and h["new_start"] <= ln < h["new_start"] + h["new_len"]:
                    span.update(range(max(ln - window, h["new_start"]), min(ln + window, h["new_start"] + h["new_len"] - 1) + 1))
            n = min(len(span), full)
            how = f"{n} of {full} lines (+-{window} around cited lines)"
        else:
            n, how = full, "whole hunk"
        lines += n
        rows.append({"hunk": hid, "path": h["path"], "kind": h["kind"], "lines": n, "of": full, "how": how})
    total = route["reading_budget"]["total_changed_lines"]
    out = {"lines": lines, "total_changed_lines": total, "ratio": round(lines / total, 4) if total else 0,
           "hunks": [r["hunk"] for r in rows if r["lines"]], "per_hunk": rows,
           "router_hunk_level": {"lines": route["reading_budget"]["lines"], "provisional": route["reading_budget"].get("provisional")},
           "method": line_level_budget.__doc__.strip().split("\n")[0]}
    adj["reading_budget_line_level"] = out
    if write:
        write_json(run / "adjudication.json", adj)
    return out
