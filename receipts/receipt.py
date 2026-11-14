"""RECEIPT: the named owner's signed statement of what was checked, what was not, and the risk they accept.
Local files only (receipt.json / receipt.md / receipt.trailer.txt). Nothing is committed, pushed or written as a git note."""
import re

import yaml

from . import config
from .util import now_iso, read_json, sha256_bytes, sha256_file, write_json

MIN_WORDS = 15
MAX_OVERLAP = 0.60
OWN_FILES = {"receipt.json", "receipt.md", "receipt.trailer.txt"}
_tok = re.compile(r"[a-z0-9_#]+")


def tokens(s):
    return _tok.findall(s.lower())


def _ai_strings(run):
    out = []

    def walk(o):
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in ("owner_decision", "owner_note"):
                    continue
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for name in ("claims.json", "refusals.json", "story.json", "prosecutor.json"):
        d = read_json(run / name)
        if d is not None:
            walk(d)
    return [s for s in out if len(tokens(s)) >= 5]


def own_words_guard(text, run):
    toks = tokens(text)
    if len(toks) < MIN_WORDS:
        return False, f"residual risk must be at least {MIN_WORDS} words in your own words (got {len(toks)})", 0.0
    mine = set(toks)
    worst, worst_s = 0.0, ""
    for s in _ai_strings(run):
        ov = len(mine & set(tokens(s))) / len(mine)
        if ov > worst:
            worst, worst_s = ov, s
    if worst >= MAX_OVERLAP:
        return False, f"{worst:.0%} of your words overlap one AI-written string (limit {MAX_OVERLAP:.0%}); rewrite it yourself: “{worst_s[:90]}…”", worst
    return True, "ok", worst


def bundle_hash(run, receipt_core):
    parts = []
    for p in sorted(run.rglob("*")):
        if p.is_file() and p.name not in OWN_FILES and not p.name.startswith("."):
            parts.append(f"{p.relative_to(run).as_posix()}:{sha256_file(p)}")
    import json
    blob = "\n".join(parts) + "\n" + json.dumps(receipt_core, sort_keys=True, ensure_ascii=False)
    return sha256_bytes(blob.encode("utf8")), len(parts)


def _evidence_sha(run, refs):
    h = []
    for r in refs or []:
        rel = r.split("#")[0]
        for base in (config.ROOT, run):
            p = (base / rel)
            if p.is_file():
                h.append(f"{rel}:{sha256_file(p)}")
                break
    return sha256_bytes("\n".join(sorted(h)).encode()) if h else None


def build(change_id, decision_file, owner_override=None, allow_unanswered=False, rehearsal=False):
    change_id = str(change_id)
    run = config.run_dir(change_id)
    dec = yaml.safe_load(open(decision_file, encoding="utf8"))
    change = read_json(run / "change.json") or {}
    route = read_json(run / "route.json") or {}
    claims = (read_json(run / "claims.json") or {})
    refusals = (read_json(run / "refusals.json") or {}).get("refusals", [])
    xray = read_json(run / "xray.json") or {}
    cit = read_json(run / "citations.json") or {}
    meta = read_json(run / "reviewer.json") or {}

    ok, msg, ov = own_words_guard(dec.get("residual_risk_owner_words", ""), run)
    if not ok:
        raise SystemExit(f"RECEIPT REFUSED (own-words guard): {msg}")
    answered = {d["id"]: d for d in dec.get("refusal_decisions", [])}
    missing = [r["id"] for r in refusals if r["id"] not in answered or not str(answered[r["id"]].get("decision", "")).strip()]
    if missing and not allow_unanswered:
        raise SystemExit(f"RECEIPT REFUSED: unanswered refusals {missing}. The owner must decide each one.")
    owner = owner_override or dec.get("owner") or config.OWNER_NAME
    if rehearsal and owner in ("", "OWNER_NAME"):
        owner = "Rehearsal Owner"

    checked, not_checked = [], []
    for c in claims.get("claims", []):
        if c.get("evidence_level") in ("E3", "E2") and c.get("status") in ("proven", "supported"):
            how = {"E3": "executed", "E2": "mechanical"}[c["evidence_level"]]
            checked.append({"claim": c["id"], "text": c.get("text"), "by": f"{c.get('verifier', '?')} ({how})",
                            "evidence_level": c["evidence_level"], "evidence_sha256": _evidence_sha(run, c.get("evidence_refs"))})
        else:
            not_checked.append({"what": f"claim {c['id']}: {c.get('text')}", "why": f"evidence level {c.get('evidence_level', 'n/a')}, status {c.get('status', 'n/a')}"})
    for g in xray.get("groups", []):
        if g.get("result") == "unprotected":
            not_checked.append({"what": f"hunks {', '.join(g.get('hunks', []))} (X-Ray group {g['id']})", "why": "no test fails when this code is reverted; owner read it by eye"})
    for rid in claims.get("uncovered_requirements", []):
        not_checked.append({"what": f"requirement {rid}", "why": "no claim covers it"})
    for x in dec.get("not_checked_extra", []) or []:
        not_checked.append(x)

    core = {
        "rehearsal": bool(rehearsal),
        "rehearsal_note": ("Rehearsal for the demo. The decisions and the risk statement were written for practice, not by an accountable owner. Not a real sign-off." if rehearsal else None),
        "change": change_id, "requirements": change.get("requirement_ids", [f"REQ-{change_id}"]),
        "base": change.get("base"), "head": change.get("head"),
        "owner": owner, "signed_at": now_iso(), "lane": route.get("lane"),
        "reading_budget": route.get("reading_budget"),
        "checked": checked, "not_checked": not_checked,
        "refusal_decisions": [{"id": r["id"], "rule": r.get("rule"), "question": r.get("question_for_owner"),
                               "decision": answered.get(r["id"], {}).get("decision"), "note": answered.get(r["id"], {}).get("note")} for r in refusals],
        "residual_risk_owner_words": dec["residual_risk_owner_words"].strip(),
        "own_words_guard": {"overlap_with_ai_text": round(ov, 3), "limit": MAX_OVERLAP, "min_words": MIN_WORDS},
        "citations_summary": cit.get("summary"),
        "reviewer": {"models": meta.get("models") or claims.get("produced_by"), "prompt_sha256": meta.get("prompt_sha256"),
                     "policy_version": f"{route.get('policy', {}).get('areas')}+{route.get('policy', {}).get('routing')}",
                     "advisory_only": True},
    }
    h, n = bundle_hash(run, core)
    core["bundle_sha256"] = h
    core["bundle_files"] = n
    write_json(run / "receipt.json", core)
    (run / "receipt.md").write_text(render_md(core), encoding="utf8")
    (run / "receipt.trailer.txt").write_text(trailer(core), encoding="utf8")
    return core


def trailer(r):
    reqs = ", ".join(r["requirements"])
    rh = "Rehearsal: true (practice run, not a real sign-off)\n" if r.get("rehearsal") else ""
    return (rh + f"Requirement: {reqs}\nReceipt: sha256:{r['bundle_sha256']}\n"
            f"Owner-Accepted-Risk: {r['residual_risk_owner_words'][:100]}\n"
            f"Reviewed-by-AI: receipts/{r['reviewer']['policy_version']} (advisory)\n"
            f"Signed-off-by: {r['owner']}\n")


def render_md(r):
    b = r.get("reading_budget") or {}
    L = [f"# Receipt: change {r['change']} ({', '.join(r['requirements'])})", ""]
    if r.get("rehearsal"):
        L += ["> **REHEARSAL.** " + r["rehearsal_note"], ""]
    L += [
         f"- Owner: **{r['owner']}**  ·  signed {r['signed_at']}  ·  lane **{r['lane']}**",
         f"- Commit: `{(r['head'] or '')[:12]}` (base `{(r['base'] or '')[:12]}`)",
         f"- Reading budget: {b.get('lines')} of {b.get('total_changed_lines')} changed lines" + (" (provisional)" if b.get("provisional") else ""),
         f"- Bundle: `sha256:{r['bundle_sha256']}` over {r['bundle_files']} evidence files", "",
         "## What was checked, and by whom or what"]
    L += [f"- {c['claim']}: {c['text']} → **{c['by']}** ({c['evidence_level']})" for c in r["checked"]] or ["- nothing proven"]
    L += ["", "## What was NOT checked, and why"]
    L += [f"- {x['what']}: {x['why']}" for x in r["not_checked"]] or ["- (nothing recorded)"]
    L += ["", "## What the AI refused to decide, and the owner's decision"]
    L += [f"- {d['id']} ({d['rule']}): {d['question']}\n  - **Decision:** {d['decision']}: {d['note'] or ''}" for d in r["refusal_decisions"]] or ["- (no refusals)"]
    L += ["", "## Residual risk the owner accepts (own words)", "", f"> {r['residual_risk_owner_words']}", "",
          "_The AI review is advice with evidence, never the approval. A named human owns this change._", ""]
    return "\n".join(L)
