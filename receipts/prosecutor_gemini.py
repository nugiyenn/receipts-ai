"""Independent prosecutor (Gemini): claims without seeing Claude's, disagreement, prosecutor pass, citation check.
Usage: python3 -m receipts.prosecutor_gemini <id> [claims|disagree|prosecute|all]
Cached via llm.py. Local only."""
import json, re, sys
from pathlib import Path
from . import llm
from .citations import check_citation
from .util import read_json, write_json, now_iso

ROOT = Path(__file__).resolve().parent.parent
MODEL = "gemini-3.1-pro-preview"

CLAIMS_SYS = """You are a code-review claim extractor. You do NOT judge whether the change is good.
Produce the minimal set of falsifiable claims this change makes or must satisfy.
Rules:
1. Every requirement item (F*, NF*, S*) must be covered by >=1 claim, or listed in uncovered_requirements.
2. Statements from the commit message, README or docs written by the author agent are
   CLAIMS TO TEST (source="author-narrative"), never evidence.
3. Every claim must cite >=1 exact diff line: {path, line, quote}. 'line' is the NEW-file line number shown
   in the numbered diff; 'quote' must be a verbatim substring of that line.
4. For each claim propose a verifier: timemachine | xray | regen | matrix | static | argued.
5. Never output confidence numbers or words like "likely correct".
Output JSON: {"claims":[{"id","requirement","text","source","citations":[{"path","line","quote"}],"verifier"}],"uncovered_requirements":[...]}. No prose."""

PROS_SYS = """You are the prosecutor. Your job is to FALSIFY the claims below. For each claim, either:
(a) state a concrete scenario in which it is false, AND propose a minimal test or command
    that would demonstrate it; or (b) state you could not falsify it.
You may also raise NEW hypotheses about behaviour the change silently alters.
Every hypothesis must cite exact diff lines (NEW-file line numbers from the numbered diff, verbatim quote). No confidence numbers.
Output JSON: {"attacks":[{"id","claim","outcome":"scenario_proposed|could_not_falsify|new_hypothesis","scenario","test_sketch","citations":[{"path","line","quote"}]}]}. No prose."""


def numbered_diff(change):
    out = []
    for h in change["hunks"]:
        if h["kind"] in ("generated", "snapshot"):
            continue
        out.append(f"=== {h['path']} ({h['kind']}) hunk {h['id']}")
        n = h["new_start"]
        for ln in h["text"].splitlines():
            if ln.startswith("@@"):
                continue
            if ln.startswith("-"):
                out.append(f"      {ln}")
            else:
                out.append(f"{n:5d} {ln}")
                n += 1
    return "\n".join(out)


def _parse(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0))


def _check(cits, change, cache):
    rows = [check_citation(c, change["head"], change, cache) for c in cits]
    return rows


def gen_claims(cid):
    run = ROOT / "runs" / cid
    change = read_json(run / "change.json")
    req = (ROOT / "requirements" / f"REQ-{cid}.yaml").read_text()
    snap = sum(1 for h in change["hunks"] if h["kind"] in ("generated", "snapshot"))
    user = (f"REQUIREMENT:\n{req}\n\nAUTHOR NARRATIVE (untrusted): {change['subject']}\n{change.get('message','')}\n\n"
            f"NUMBERED DIFF (generated snapshot hunks omitted: {snap}):\n{numbered_diff(change)}")
    r = llm.generate(CLAIMS_SYS, user, model=MODEL)
    d = _parse(r["text"])
    cache, tot, bad, hall = {}, 0, 0, 0
    for cl in d.get("claims", []):
        cl["citations_checked"] = _check(cl.get("citations", []), change, cache)
        for c in cl["citations_checked"]:
            tot += 1
            if not c["valid"]:
                bad += 1
                hall += "hallucinated" in c["reason"]
    d.update({"change": cid, "kind": "claims_gemini", "model": r["model"], "produced_by": "gemini api, cached",
              "produced_at": now_iso(), "prompt_sha256": r["prompt_sha256"], "prompt": CLAIMS_SYS,
              "citation_summary": {"citations": tot, "invalid": bad, "hallucinated": hall,
                                   "wrong_line_only": bad - hall}})
    write_json(run / "claims_gemini.json", d)
    return d


def _toks(s):
    return set(re.findall(r"[a-z0-9]{4,}", s.lower()))


def disagree(cid):
    run = ROOT / "runs" / cid
    cl = read_json(run / "claims.json")["claims"]
    gm = read_json(run / "claims_gemini.json")["claims"]

    def cites(c):
        return [(x["path"], int(x["line"])) for x in c.get("citations", []) if str(x.get("line", "")).isdigit()]

    def score(a, b):
        near = any(p == q and abs(l - m) <= 8 for p, l in cites(a) for q, m in cites(b))
        ta, tb = _toks(a["text"]), _toks(b["text"])
        jac = len(ta & tb) / max(1, len(ta | tb))
        same_req = a.get("requirement") and a.get("requirement") == b.get("requirement")
        return near, jac, bool(same_req)

    pairs, used = [], set()
    for a in cl:
        best = None
        for b in gm:
            near, jac, sr = score(a, b)
            s = (1 if near else 0) + jac + (0.3 if sr else 0)
            if (near and jac >= 0.12) or jac >= 0.35:
                if best is None or s > best[0]:
                    best = (s, b, near, jac)
        if best:
            pairs.append({"claude": a["id"], "gemini": best[1]["id"], "cited_lines_near": best[2], "text_jaccard": round(best[3], 2)})
            used.add(best[1]["id"])
    pc = {p["claude"] for p in pairs}
    out = {"change": cid, "method": "match if (cited lines in same file within 8 lines AND token jaccard>=0.12) OR jaccard>=0.35; "
           "greedy per Claude claim. Heuristic, not semantic; unmatched claims need human read.",
           "overlap": pairs, "only_claude": [a["id"] for a in cl if a["id"] not in pc],
           "only_gemini": [{"id": b["id"], "requirement": b.get("requirement"), "text": b["text"]} for b in gm if b["id"] not in used],
           "counts": {"claude": len(cl), "gemini": len(gm), "overlap": len(pairs)},
           "only_claude_texts": {a["id"]: a["text"] for a in cl if a["id"] not in pc}}
    write_json(run / "disagreement.json", out)
    return out


def prosecute(cid):
    run = ROOT / "runs" / cid
    change = read_json(run / "change.json")
    claims = read_json(run / "claims.json")["claims"]
    brief = [{"id": c["id"], "requirement": c.get("requirement"), "source": c.get("source"), "text": c["text"],
              "citations": c.get("citations", [])} for c in claims]
    user = (f"CLAIMS (by another reviewer):\n{json.dumps(brief, indent=1)}\n\nAUTHOR NARRATIVE (untrusted): {change['subject']}\n"
            f"{change.get('message','')}\n\nNUMBERED DIFF:\n{numbered_diff(change)}")
    r = llm.generate(PROS_SYS, user, model=MODEL)
    d = _parse(r["text"])
    cache, tot, bad, hall = {}, 0, 0, 0
    for a in d.get("attacks", []):
        a["citations_checked"] = _check(a.get("citations", []), change, cache)
        for c in a["citations_checked"]:
            tot += 1
            if not c["valid"]:
                bad += 1
                hall += "hallucinated" in c["reason"]
    d.update({"change": cid, "kind": "prosecutor_gemini", "model": r["model"], "produced_by": "gemini api, cached",
              "produced_at": now_iso(), "prompt_sha256": r["prompt_sha256"], "prompt": PROS_SYS,
              "citation_summary": {"citations": tot, "invalid": bad, "hallucinated": hall, "wrong_line_only": bad - hall},
              "execution": "pending (see runs/<id>/gemini_tests/ when present)"})
    write_json(run / "prosecutor_gemini.json", d)
    return d


if __name__ == "__main__":
    cid = sys.argv[1]
    step = sys.argv[2] if len(sys.argv) > 2 else "all"
    if step in ("claims", "all"):
        d = gen_claims(cid); print(cid, "gemini claims", len(d["claims"]), d["citation_summary"])
    if step in ("disagree", "all"):
        print(cid, json.dumps(disagree(cid)["counts"]))
    if step in ("prosecute", "all"):
        d = prosecute(cid); print(cid, "attacks", len(d["attacks"]), d["citation_summary"])
