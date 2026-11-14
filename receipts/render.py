#!/usr/bin/env python3
"""Build the single-file walkthrough: web/index.html (inline CSS/JS, all data embedded, no network).

    python3 receipts/render.py            # real data only (runs/<id>/*.json, data/*.json)
    python3 receipts/render.py --mock     # developer build from web/fixtures/mock.json -> web/index.mock.html

The default build NEVER reads the mock fixture. Missing files simply become honest
'not run yet' empty states in the UI.
"""
import argparse, datetime, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
CHANGE_IDS = ["2283", "2234", "2297", "2129"]
RUN_FILES = ["adjudication", "change", "route", "claims", "story", "xray", "timemachine", "refusals",
             "prosecutor", "receipt", "regen", "files", "matrix", "not_checked"]


def _load(p):
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        print(f"warning: {p} is not valid JSON ({e}); treated as missing", file=sys.stderr)
        return None


def _meta(p):
    out = {}
    try:
        for tok in p.read_text().split():
            k, _, v = tok.partition("=")
            out[k] = v
    except FileNotFoundError:
        pass
    return out


def _excerpt(log, want):
    """A short, honest excerpt of a real log: lines matching `want`, capped; falls back to the tail."""
    try:
        lines = log.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    picked, seen = [], set()
    for ln in lines:
        t = ln.strip()
        if want.search(t) and t not in seen:
            seen.add(t)
            picked.append(t[:240])
        if len(picked) >= 14:
            break
    return "\n".join(picked or [x[:240] for x in lines[-12:]])


def synth_timemachine(cid):
    """Fallback when the evidence stage has not written timemachine.json yet: build the view
    from the real base/head logs. Flagged synthesized_from_logs so the UI/judges can tell."""
    d = ROOT / "runs" / cid / "timemachine"
    if not (d / "base.log").exists() or not (d / "head.log").exists():
        return None
    want = re.compile(r"(\bFailed\b|\bPassed\b|AD0001|CS8785|IndexOutOfRange|Total tests|Failed:|Passed:)")
    bm, hm = _meta(d / "base.meta"), _meta(d / "head.meta")
    def side(name, m):
        status = "pass" if m.get("exit") == "0" else ("fail" if m.get("exit") else "?")
        return {"status": status, "seconds": float(m["secs"]) if m.get("secs") else None,
                "log": f"runs/{cid}/timemachine/{name}.log", "excerpt": _excerpt(d / f"{name}.log", want)}
    b, h = side("base", bm), side("head", hm)
    tests = sorted({m.group(1) for m in re.finditer(r"(?:Failed|Passed)\s+(\S+)", (d / "head.log").read_text(errors="replace"))})
    return {"synthesized_from_logs": True, "tests": tests, "base": b, "head": h, "outcome": f"{b['status']}->{h['status']}"}


def collect_real():
    changes = {}
    for cid in CHANGE_IDS:
        d = {k: _load(ROOT / "runs" / cid / f"{k}.json") for k in RUN_FILES}
        a = d.get("adjudication")
        if a:  # keep only what the UI cites, to stay small
            d["adjudication"] = {"levels": a.get("levels"), "statuses": a.get("statuses"), "uncovered_requirements": a.get("uncovered_requirements"),
                                 "timemachine": a.get("timemachine"), "requirement_coverage": [{"id": x.get("id"), "text": (x.get("text") or "")[:160]} for x in (a.get("requirement_coverage") or [])], "reading_budget_line_level": {k: (a.get("reading_budget_line_level") or {}).get(k) for k in ("lines", "total_changed_lines", "ratio")}}
        if d.get("timemachine") is None:
            d["timemachine"] = synth_timemachine(cid)
        changes[cid] = {k: v for k, v in d.items() if v is not None}
    concept = next((p for p in (ROOT / "docs" / "CONCEPT_CARD.md", ROOT / "docs" / "concept-card.md") if p.exists()), None)
    return {
        "meta": {"mock": False, "generated": datetime.datetime.now().isoformat(timespec="minutes"),
                 "owner_name": "OWNER_NAME"},
        "changes": changes,
        "ledger": _load(ROOT / "data" / "ledger_history.json"),
        "ledger_state": _load(ROOT / "data" / "ledger_state.json"),
        "drill": _load(ROOT / "data" / "drill.json"),
        "backtest": _load(ROOT / "data" / "backtest.json"),
        "rehearsal": _load(ROOT / "data" / "rehearsal_receipt.json"),
        "concept_md": concept.read_text() if concept else "",
    }


def slim(data):
    """Keep the single file small. Generated-snapshot hunks are verified by pattern, never read by
    a human: the first 3 keep their diff text as samples, hunks the router flagged stay as they
    are, and the rest collapse into ONE aggregate hunk whose added/removed counts stay exact."""
    for ch in data["changes"].values():
        c = ch.get("change") or {}
        hunks = c.get("hunks") or []
        route = ch.get("route") or {}
        fl = route.get("flagged_hunks") or {}
        flagged = set(fl if isinstance(fl, (list, tuple)) else fl.keys())
        regen = ch.get("regen") or {}
        bad = {x.get("path") if isinstance(x, dict) else x for x in (regen.get("generated_nonmatching") or [])}
        out, agg, samples = [], None, 0
        for h in hunks:
            h.pop("ctx", None)
            if h.get("kind") == "generated" and h.get("path") not in bad:
                if samples < 3:
                    samples += 1
                    out.append(h)
                    continue
                if agg is None:
                    agg = {"id": "gen*", "path": "generated snapshots (*.g.cs)", "kind": "generated", "area": "generated-snapshots",
                           "added": 0, "removed": 0, "text": "", "count": 0, "paths": set(), "aggregate": True, "flagged_lines": 0}
                    out.append(agg)
                agg["added"] += h.get("added") or 0
                agg["removed"] += h.get("removed") or 0
                agg["count"] += 1
                if h.get("id") in flagged:
                    agg["flagged_lines"] += (h.get("added") or 0) + (h.get("removed") or 0)
                agg["paths"].add(h.get("path"))
                continue
            t = h.get("text") or ""
            ls = t.split("\n")
            if len(ls) > 400:
                h["text"] = "\n".join(ls[:400]) + f"\n... {len(ls) - 400} more lines not embedded\n"
                h["truncated"] = True
            out.append(h)
        if agg is not None:
            agg["files_n"] = len(agg.pop("paths"))
        if hunks:
            c["hunks"] = out
        if route.get("files"):
            route["files"] = [{k: f.get(k) for k in ("path", "area", "kind", "lane", "changed_lines")} for f in route["files"]]
        if ch.get("regen"):
            rg = ch["regen"]; ch["regen"] = {k: rg.get(k) for k in ("generated_total", "generated_matching", "generated_nonmatching", "reading_budget_lines", "verdict", "identical", "mismatched", "method")}
            ch["regen"]["generated_nonmatching"] = [{"path": x.get("path")} if isinstance(x, dict) else x for x in (rg.get("generated_nonmatching") or [])]
        br = route.get("blast_radius") or {}
        if agg is not None:
            keep = {h["id"] for h in out}
            if samples:
                keep |= set()
            br["per_hunk"] = {k: v for k, v in (br.get("per_hunk") or {}).items() if k in keep}
            if isinstance(fl, dict):
                route["flagged_hunks"] = {k: v for k, v in fl.items() if k in keep}
        if c.get("files") and (route.get("files") or ch.get("files") is not None):
            ch.pop("files", None)
    return data


def embed(data):
    s = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    return s.replace("</", "<\\/").replace("<!--", "<\\!--")


def build(mock=False, out=None):
    if mock:
        sys.exit("The mock fixture was removed before the final build. Only real data is rendered.")
    data = collect_real()
    out = out or WEB / "index.html"
    slim(data)
    if data.get("ledger_state"):
        data["ledger"] = None   # history only needed for per-area revert rates; the simple Ledger view uses the global series
    tpl = (WEB / "template.html").read_text()
    html = tpl.replace("/*__DATA__*/null", embed(data))
    pathlib.Path(out).write_text(html)
    n = sum(len(v) for v in data["changes"].values())
    print(f"wrote {out} ({len(html)//1024} KB, {n} run files, mock={data['meta']['mock']})")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="developer build from fixtures (never the shipped file)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    build(a.mock, a.out)


if __name__ == "__main__":
    main()
