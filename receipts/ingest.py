"""INGEST: parse base..head diff into files + hunks, classify kinds/areas, write runs/<id>/change.json."""
import re
from pathlib import Path

import yaml

from . import config
from .util import git, glob_to_regex, read_json, write_json

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


def load_areas():
    spec = yaml.safe_load((config.POLICY / "areas.yaml").read_text(encoding="utf8"))
    out = []
    for a in spec["areas"]:
        out.append({**a, "_res": [glob_to_regex(g) for g in a["globs"]]})
    return spec.get("version", "areas"), out


def area_of(path, areas):
    for a in areas:
        if any(r.match(path) for r in a["_res"]):
            return a
    return areas[-1]


def classify_kind(path: str, all_paths: set) -> str:
    p = path.replace("\\", "/")
    if p.endswith(".g.cs") or "/Resources/" in p or p.endswith(".verified.cs") or p.endswith(".verified.txt"):
        return "generated"
    if p.startswith("tests/") or "/tests/" in p:
        return "test"
    if p.endswith(".md") or p.startswith("doc/") or p.startswith("docs/"):
        return "doc"
    if p.endswith(".tt"):
        return "template"
    if p.endswith(".cs") and (p[:-3] + ".tt") in all_paths:
        return "template-output"        # T4 output next to its .tt; verified by regeneration
    return "src"


def parse_diff(diff_text: str):
    files, cur, hunk = [], None, None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            cur = {"a": m.group(1), "b": m.group(2), "status": "modified", "hunks": [], "binary": False}
            files.append(cur)
            hunk = None
        elif cur is None:
            continue
        elif hunk is None and line.startswith("new file mode"):
            cur["status"] = "added"
        elif hunk is None and line.startswith("deleted file mode"):
            cur["status"] = "deleted"
        elif hunk is None and line.startswith("rename from"):
            cur["status"] = "renamed"
        elif hunk is None and line.startswith("Binary files"):
            cur["binary"] = True
        elif line.startswith("@@"):
            m = HUNK_RE.match(line)
            if not m:
                continue
            hunk = {
                "old_start": int(m.group(1)), "old_len": int(m.group(2) or 1),
                "new_start": int(m.group(3)), "new_len": int(m.group(4) or 1),
                "ctx": m.group(5).strip(), "lines": [line], "added": 0, "removed": 0,
            }
            cur["hunks"].append(hunk)
        elif hunk is not None:
            if line.startswith("\\"):
                hunk["lines"].append(line)
                continue
            hunk["lines"].append(line)
            if line.startswith("+"):
                hunk["added"] += 1
            elif line.startswith("-"):
                hunk["removed"] += 1
    return files


def ingest(change_id: str, write=True):
    change_id = str(change_id)
    branch = config.BRANCHES[change_id]
    head = git("rev-parse", branch).strip()
    base = git("rev-parse", branch + "~1").strip()
    subject = git("log", "-1", "--format=%s", head).strip()
    message = git("log", "-1", "--format=%B", head).strip()
    diff = git("diff", "--no-color", "-U3", "--no-ext-diff", base, head)
    parsed = parse_diff(diff)
    areas_ver, areas = load_areas()
    paths = {(f["a"] if f["status"] == "deleted" else f["b"]) for f in parsed}

    files, hunks, n = [], [], 0
    for f in parsed:
        path = f["a"] if f["status"] == "deleted" else f["b"]
        kind = classify_kind(path, paths)
        area = area_of(path, areas)
        hids, fa, fr = [], 0, 0
        for h in f["hunks"]:
            n += 1
            hid = f"h{n}"
            hids.append(hid)
            fa += h["added"]
            fr += h["removed"]
            hunks.append({
                "id": hid, "path": path, "kind": kind, "area": area["name"],
                "old_start": h["old_start"], "old_len": h["old_len"],
                "new_start": h["new_start"], "new_len": h["new_len"],
                "ctx": h["ctx"], "added": h["added"], "removed": h["removed"],
                "text": "\n".join(h["lines"]), "group": None,
            })
        files.append({"path": path, "area": area["name"], "kind": kind, "status": f["status"],
                      "added": fa, "removed": fr, "hunks": hids, "binary": f["binary"]})

    req_ids = [f"REQ-{change_id}"]
    out = {
        "id": change_id, "requirement_ids": req_ids, "repo": "../repo",
        "branch": branch.replace("origin/", ""), "base": base, "head": head,
        "subject": subject, "message": message, "areas_version": areas_ver,
        "totals": {
            "files": len(files), "hunks": len(hunks),
            "added": sum(f["added"] for f in files), "removed": sum(f["removed"] for f in files),
            "changed_lines": sum(f["added"] + f["removed"] for f in files),
            "by_kind": {k: sum(1 for f in files if f["kind"] == k) for k in sorted({f["kind"] for f in files})},
        },
        "files": files, "hunks": hunks,
    }
    if write:
        write_json(config.run_dir(change_id) / "change.json", out)
    return out


def hunk_for_line(change, path, line):
    """Return the hunk id whose new-side range covers (path, line), else None."""
    for h in change["hunks"]:
        if h["path"] == path and h["new_start"] <= line < h["new_start"] + max(h["new_len"], 1):
            return h["id"]
    return None
