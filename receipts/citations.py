"""Citation validator (anti-hallucination): every claim citation {path,line,quote} must exist in the HEAD version at that line."""
import re

from . import config
from .ingest import hunk_for_line
from .util import git, now_iso, read_json, write_json

_ws = re.compile(r"\s+")


def norm(s: str) -> str:
    return _ws.sub(" ", s.strip())


def _file_lines(head, path, cache):
    if path not in cache:
        try:
            cache[path] = git("show", f"{head}:{path}").splitlines()
        except RuntimeError:
            cache[path] = None
    return cache[path]


def check_citation(c, head, change, cache):
    path, quote = c.get("path"), c.get("quote", "")
    try:
        line = int(c.get("line"))
    except (TypeError, ValueError):
        return {**c, "valid": False, "reason": "missing or non-numeric line"}
    lines = _file_lines(head, path, cache)
    if lines is None:
        return {**c, "valid": False, "reason": "file does not exist at head"}
    if not norm(quote):
        return {**c, "valid": False, "reason": "empty quote"}
    if not (1 <= line <= len(lines)):
        return {**c, "valid": False, "reason": f"line {line} out of range (file has {len(lines)} lines)"}
    if norm(quote) in norm(lines[line - 1]):
        return {**c, "valid": True, "reason": "exact quote at cited line",
                "in_diff": hunk_for_line(change, path, line) is not None,
                "hunk": hunk_for_line(change, path, line)}
    near = [i + 1 for i, t in enumerate(lines) if norm(quote) in norm(t)]
    if near:
        return {**c, "valid": False, "reason": f"quote exists but at line(s) {near[:5]}, not {line} (wrong line number)", "actual_lines": near[:5]}
    return {**c, "valid": False, "reason": "quote not found in file (hallucinated citation)"}


def validate(change_id: str, write=True):
    change_id = str(change_id)
    run = config.run_dir(change_id)
    change = read_json(run / "change.json")
    claims = (read_json(run / "claims.json") or {}).get("claims")
    if change is None:
        raise SystemExit(f"runs/{change_id}/change.json missing: run `review --change {change_id}` first")
    if claims is None:
        out = {"change": change_id, "checked_at": now_iso(), "status": "no claims.json yet", "summary": {"citations": 0, "valid": 0, "invalid": 0, "claims_invalid": 0}, "claims": []}
        if write:
            write_json(run / "citations.json", out)
        return out
    cache, rows, tot, ok = {}, [], 0, 0
    for cl in claims:
        cits = [check_citation(c, change["head"], change, cache) for c in cl.get("citations", [])]
        tot += len(cits)
        ok += sum(1 for c in cits if c["valid"])
        all_valid = bool(cits) and all(c["valid"] for c in cits)
        rows.append({"claim": cl["id"], "all_valid": all_valid,
                     "note": None if cits else "claim has no citations (E0)",
                     "citations": cits})
    out = {"change": change_id, "checked_at": now_iso(), "head": change["head"],
           "summary": {"citations": tot, "valid": ok, "invalid": tot - ok,
                       "claims": len(rows), "claims_invalid": sum(1 for r in rows if not r["all_valid"]),
                       "hallucination_rate": round((tot - ok) / tot, 4) if tot else 0.0},
           "claims": rows}
    if write:
        write_json(run / "citations.json", out)
    return out
