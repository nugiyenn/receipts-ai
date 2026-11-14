"""One place that explains the reading-budget numbers a change can show.

  headline (route.json reading_budget.lines)  line level: flagged src/template hunks whole, doc and test hunks only near cited evidence gaps
  hunk_level (reading_budget.hunk_level_lines) whole flagged hunks, what the router flags before the line-level cut
  regen_ceiling (regen.json reading_budget_lines) every non-snapshot changed line plus the changed lines of snapshots that do not
                                                   match the expected pattern. A looser, earlier estimate that only needs regen.json.
The headline is the number the UI and docs quote. The other two are kept so a reader can see where it came from."""
from . import config
from .util import read_json, write_json


def regen_ceiling(change_id):
    run = config.RUNS / str(change_id)
    ch, rg = read_json(run / "change.json"), read_json(run / "regen.json")
    if not (ch and rg):
        return None
    bad = {x["path"] if isinstance(x, dict) else x for x in rg.get("generated_nonmatching", [])}
    lines = sum(f["added"] + f["removed"] for f in ch["files"] if f["kind"] != "generated" or f["path"] in bad)
    return lines


def views(change_id):
    run = config.RUNS / str(change_id)
    rb = (read_json(run / "route.json") or {}).get("reading_budget") or {}
    return {"headline_line_level": rb.get("lines"), "hunk_level": rb.get("hunk_level_lines"), "regen_ceiling": regen_ceiling(change_id),
            "total_changed_lines": rb.get("total_changed_lines")}


def annotate(change_id):
    """Write budget_note into route.json and regen.json so the numbers explain each other."""
    run = config.RUNS / str(change_id)
    v = views(change_id)
    if v["headline_line_level"] is None:
        return None
    parts = [f"Headline {v['headline_line_level']} of {v['total_changed_lines']} changed lines is the line-level budget (route.json)."]
    if v["hunk_level"] is not None:
        parts.append(f"{v['hunk_level']} is the same flags counted as whole hunks.")
    if v["regen_ceiling"] is not None:
        parts.append(f"{v['regen_ceiling']} (regen.json) counts every non-snapshot changed line plus the snapshots that do not match, "
                     "so it is a looser ceiling made before claims and refusals existed.")
    note = {"headline_line_level": v["headline_line_level"], "hunk_level": v["hunk_level"], "regen_ceiling": v["regen_ceiling"],
            "explanation": " ".join(parts), "derived_by": "receipts/budget.py"}
    for name in ("route.json", "regen.json"):
        d = read_json(run / name)
        if d is not None:
            d["budget_note"] = note
            write_json(run / name, d)
    return note
