"""python -m receipts <command>   (run from the receipts/ directory)"""
import argparse
import http.server
import json
import socketserver
import sys
import threading
import webbrowser
from functools import partial

from . import config


def _cached_summary(change):
    """No git clone next to this folder: print the numbers already stored in runs/ instead of recomputing."""
    run = config.RUNS / change
    try:
        route = json.loads((run / "route.json").read_text())
        adj = json.loads((run / "adjudication.json").read_text())
    except OSError:
        print(f"no cached run for change {change}")
        return 1
    b = route["reading_budget"]
    print(f"change {change}: lane {route['lane']} · reading budget {b['lines']} of {b['total_changed_lines']} changed lines")
    print(f"  claims by level {adj['levels']} · statuses {adj['statuses']}")
    print(f"  (cached numbers from runs/{change}/. No git clone found at {config.REPO}; set RECEIPTS_REPO to recompute.)")
    return 0


def _adjudicate(a):
    if not config.REPO.exists():
        return _cached_summary(a.change)
    from .evidence import adjudicate
    o = adjudicate.adjudicate(a.change)
    print(f"change {a.change}: levels {o['levels']} · statuses {o['statuses']}")
    if o["timemachine"]:
        t = o["timemachine"]
        print(f"  time machine: {t['genuine_fail_to_pass']} of {t['tests']} tests fail->pass; {t['pass_on_base']} pass on base (prove nothing)")
    print(f"  requirement coverage: {sum(1 for c in o['requirement_coverage'] if c['coverage']=='evidenced')} evidenced, "
          f"{sum(1 for c in o['requirement_coverage'] if c['coverage']=='weak')} weak, {len(o['uncovered_requirements'])} uncovered")
    print(f"  wrote runs/{a.change}/claims.json (original kept as claims.llm.json) + adjudication.json")


def _review(a):
    if not config.REPO.exists():
        return _cached_summary(a.change)
    from . import citations, router
    from .evidence import adjudicate
    if (config.RUNS / a.change / "claims.json").exists():
        adjudicate.adjudicate(a.change)          # sets evidence levels first so the router sees them
    r = router.route(a.change)
    if (config.RUNS / a.change / "claims.json").exists():
        adjudicate.line_level_budget(a.change)   # line-level budget next to the router's hunk-level one
        _ll = json.loads((config.RUNS / a.change / "adjudication.json").read_text()).get("reading_budget_line_level")
        if _ll and r["lane"] != "L3":            # headline budget = line level; hunk level kept for audit
            rb = r["reading_budget"]
            rb["hunk_level_lines"] = rb["lines"]
            rb["lines"], rb["ratio"], rb["hunks"] = _ll["lines"], _ll["ratio"], len(_ll["hunks"])
            rb["basis"] = "line-level: flagged src/template hunks whole; doc/test hunks only lines near cited evidence gaps"
            (config.RUNS / a.change / "route.json").write_text(json.dumps(r, indent=2))
    from . import budget
    budget.annotate(a.change)
    cit = citations.validate(a.change) if (config.RUNS / a.change / "claims.json").exists() else None
    b = r["reading_budget"]
    print(f"change {a.change}: lane {r['lane']} · reading budget {b['lines']} of {b['total_changed_lines']} changed lines "
          f"({b['hunks']} hunks){' [provisional: xray pending]' if b['provisional'] else ''}")
    for x in r["reasons"]:
        print(f"  {x['rule']:5} {x['lane']}  {x['why']}")
    ll = (json.loads((config.RUNS / a.change / "adjudication.json").read_text()) if (config.RUNS / a.change / "adjudication.json").exists() else {}).get("reading_budget_line_level")
    if ll:
        print(f"  line-level reading budget: {ll['lines']} of {ll['total_changed_lines']} changed lines ({ll['ratio']:.1%}); router hunk-level: {ll['router_hunk_level']['lines']}")
    print(f"  blast radius: {r['blast_radius']['top_symbol']} ({r['blast_radius']['max_references']} refs, threshold {r['blast_radius']['threshold']})")
    if cit and cit["summary"].get("citations"):
        s = cit["summary"]
        print(f"  citations: {s['valid']}/{s['citations']} valid, {s['claims_invalid']} claim(s) with an invalid citation")
    print(f"  wrote runs/{a.change}/route.json" + (" + citations.json" if cit else ""))


def _receipt(a):
    from . import receipt
    r = receipt.build(a.change, a.owner_decision_file, owner_override=a.owner, allow_unanswered=a.allow_unanswered, rehearsal=a.rehearsal)
    print(f"receipt signed by {r['owner']}: {len(r['checked'])} checked, {len(r['not_checked'])} not checked, "
          f"{len(r['refusal_decisions'])} refusal decision(s)\n  bundle sha256:{r['bundle_sha256']}\n  files: runs/{a.change}/receipt.{{json,md}} + receipt.trailer.txt")


def _ledger(a):
    from . import ledger
    if a.regen:
        import subprocess
        subprocess.run([sys.executable, str(config.ROOT / "scripts" / "gen_ledger.py")], check=True)
        return
    ledger.print_summary(ledger.build(applies_to_routing=a.apply))


def _drill(a):
    from . import drill
    if a.action == "plant":
        print(drill.plant(a.change, a.canary))
    elif a.action == "unplant":
        drill.unplant(a.change, a.canary)
    else:
        o = drill.score()
        ov = o["overall"]
        line = f"canary recall (union of signals) {ov['caught']}/{ov['planted']} = {ov['recall_union']} ({ov['not_run']} not run); missed: {o['missed']}"
        if isinstance(ov.get("recall_best_single"), dict):
            b, n = ov["recall_best_single"], ov["recall_no_llm"]
            line += f"\n  best single reviewer: {b['reviewer']} {b['caught']}/{b['planted']}; no LLM: {n['caught']}/{n['planted']}"
        print(line)
        for ar, e in o["ledger_effect"].items():
            if e["lane_before"] != e["lane_after"]:
                print(f"  ledger: {ar} {e['lane_before']} -> {e['lane_after']} ({e['reason']})")


def _backtest(a):
    from . import backtest
    o = backtest.run()
    print(json.dumps({"summary": o["summary"], "confusion_by_lane": o["confusion_by_lane"], "interpretation": o["interpretation"]}, indent=2))


def _pr_comment(a):
    from . import prcomment
    sys.stdout.write(prcomment.build(a.change))


def _required_owner(a):
    from . import owners
    o = owners.required(a.change, a.codeowners)
    print(json.dumps(o, indent=2))
    return 0 if o["owners"] else 1


def _citations(a):
    from . import citations
    print(json.dumps(citations.validate(a.change)["summary"], indent=2))


def _demo(a):
    web = config.WEB
    if not (web / "index.html").exists():
        print("web/index.html not found yet", file=sys.stderr)
        return 1
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(config.ROOT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", a.port), handler) as srv:
        url = f"http://localhost:{a.port}/web/index.html"
        print(f"serving {config.ROOT} on {url}  (Ctrl-C to stop; localhost only, nothing is published)")
        if not a.no_open:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="receipts", description="Receipts: claim-based review of agent-written PRs (local only).")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("review", help="ingest + route + citations for a change"); s.add_argument("--change", required=True); s.set_defaults(f=_review)
    s = sub.add_parser("adjudicate", help="set claim evidence levels from run artifacts (deterministic)"); s.add_argument("--change", required=True); s.set_defaults(f=_adjudicate)
    s = sub.add_parser("receipt", help="owner signs: writes receipt.json/.md/.trailer.txt")
    s.add_argument("--change", required=True); s.add_argument("--owner-decision-file", required=True)
    s.add_argument("--owner"); s.add_argument("--allow-unanswered", action="store_true")
    s.add_argument("--rehearsal", action="store_true", help="label the receipt as a practice run (not a real sign-off)"); s.set_defaults(f=_receipt)
    s = sub.add_parser("ledger", help="compute trust ledger state from data/ledger_history.json")
    s.add_argument("--regen", action="store_true", help="regenerate SYNTHETIC history (seeded)")
    s.add_argument("--apply", action="store_true", help="let the ledger lanes affect routing (default: off, history is synthetic)"); s.set_defaults(f=_ledger)
    s = sub.add_parser("drill", help="canary drill: score | plant | unplant")
    s.add_argument("action", nargs="?", default="score", choices=["score", "plant", "unplant"])
    s.add_argument("--change", default="2283"); s.add_argument("--canary"); s.set_defaults(f=_drill)
    s = sub.add_parser("backtest", help="routing backtest on real repo history (heuristic)"); s.set_defaults(f=_backtest)
    s = sub.add_parser("pr-comment", help="print the markdown PR comment for a change"); s.add_argument("--change", required=True); s.set_defaults(f=_pr_comment)
    s = sub.add_parser("required-owner", help="CODEOWNERS entries that must sign (owner of the highest-lane file)")
    s.add_argument("--change", required=True); s.add_argument("--codeowners", default=str(config.ROOT / "integration" / "CODEOWNERS.example")); s.set_defaults(f=_required_owner)
    s = sub.add_parser("citations", help="validate claim citations"); s.add_argument("--change", required=True); s.set_defaults(f=_citations)
    s = sub.add_parser("demo", help="serve the walkthrough on localhost")
    s.add_argument("--port", type=int, default=config.DEMO_PORT); s.add_argument("--no-open", action="store_true"); s.set_defaults(f=_demo)
    a = p.parse_args(argv)
    return a.f(a) or 0
