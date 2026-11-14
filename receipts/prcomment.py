"""PR comment: the one markdown comment the reference workflow posts for a change.

Built only from files in runs/<id>/ (story, claims, route, refusals, xray, adjudication). No model call.
The first line is an HTML marker so a workflow can find and update its own comment instead of adding a new one."""
from . import config
from .util import read_json

LEVEL = {"E3": "E3 ran", "E2": "E2 checked", "E1": "E1 argued", "E0": "E0 none"}


def _cell(s, n=140):
    s = " ".join(str(s or "").split()).replace("|", "/")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def build(change_id):
    cid = str(change_id)
    run = config.RUNS / cid
    route = read_json(run / "route.json") or {}
    claims = (read_json(run / "claims.json") or {}).get("claims", [])
    story = (read_json(run / "story.json") or {}).get("sentences", [])
    refusals = (read_json(run / "refusals.json") or {}).get("refusals", [])
    xray = read_json(run / "xray.json") or {}
    adj = read_json(run / "adjudication.json") or {}
    receipt = read_json(run / "receipt.json") or {}
    rb = route.get("reading_budget") or {}
    reqs = (read_json(run / "change.json") or {}).get("requirement_ids", [f"REQ-{cid}"])

    L = [f"<!-- receipts:pr-comment change={cid} -->",
         f"### Receipts: change {cid} ({', '.join(reqs)})", ""]
    L.append(f"**Lane {route.get('lane', '?')}.** Read {rb.get('lines', '?')} of {rb.get('total_changed_lines', '?')} changed lines"
             + (" (provisional, X-Ray not run for this change)" if rb.get("provisional") else "") + ". "
             "The AI review is advice with evidence. It does not approve anything.")
    L.append("")
    if story:
        L += ["**What the change does**", ""]
        L += [f"- {s['text']} [{', '.join(s.get('claims', []))}]" for s in story]
        L.append("")
    L += ["**Claims**", "", "| Claim | Evidence | Status | Statement |", "|---|---|---|---|"]
    for c in claims:
        L.append(f"| {c['id']} | {LEVEL.get(c.get('evidence_level'), c.get('evidence_level') or 'pending')} | {c.get('status', 'pending')} | {_cell(c.get('text'))} |")
    L.append("")
    if refusals:
        L += ["**Needs an answer from the owner**", ""]
        for r in refusals:
            L.append(f"- **{r['id']}** ({r.get('rule', '')}): {_cell(r.get('question_for_owner'), 260)}")
        L.append("")
    nc = []
    for c in claims:
        if not (c.get("evidence_level") in ("E3", "E2") and c.get("status") in ("proven", "supported")):
            nc.append(f"claim {c['id']}: evidence {c.get('evidence_level', 'n/a')}, status {c.get('status', 'n/a')}")
    for g in xray.get("groups", []):
        if g.get("result") == "unprotected":
            nc.append(f"hunks {', '.join(g.get('hunks', []))}: no test fails when they are reverted")
    nc += [f"requirement {r}: no claim covers it" for r in adj.get("uncovered_requirements", [])]
    tm = adj.get("timemachine") or {}
    if tm.get("tests_that_prove_nothing"):
        nc.append(f"{tm.get('pass_on_base')} of {tm.get('tests')} new tests also pass on the old code")
    L += ["**Not checked**", ""] + ([f"- {x}" for x in nc] or ["- nothing recorded"]) + [""]
    if receipt:
        tag = " (rehearsal)" if receipt.get("rehearsal") else ""
        L.append(f"Receipt{tag}: signed by {receipt.get('owner')}, `sha256:{receipt.get('bundle_sha256', '')[:16]}…`")
    else:
        L.append(f"Status check `receipts/owner-signed` stays pending until the CODEOWNER of the highest-lane area comments `/receipts sign`.")
    return "\n".join(L) + "\n"
