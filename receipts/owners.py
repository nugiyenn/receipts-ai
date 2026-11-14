"""Which CODEOWNERS entry must sign a change: the owner of the highest-lane file in runs/<id>/route.json.

Matching follows the usual CODEOWNERS rules in simplified form: the last matching pattern wins, a leading
slash anchors the pattern at the repository root, a trailing slash matches a directory, * does not cross
a slash and ** does. It is a reference implementation for the integration, not a full gitignore engine."""
import re

from . import config
from .util import read_json

LANE_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


def _regex(pattern):
    anchored = pattern.startswith("/")
    p = pattern.strip("/") if anchored else pattern.rstrip("/")
    is_dir = pattern.endswith("/")
    out, i = "", 0
    while i < len(p):
        if p.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif p.startswith("**", i):
            out += ".*"; i += 2
        elif p[i] == "*":
            out += "[^/]*"; i += 1
        elif p[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(p[i]); i += 1
    prefix = "^" if anchored or "/" in p else "^(?:.*/)?"
    tail = "(?:/.*)?$" if is_dir or "." not in p.split("/")[-1] else "$"
    return re.compile(prefix + out + tail)


def parse(text):
    rules = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        pat, *owners = line.split()
        rules.append((pat, _regex(pat), owners))
    return rules


def owners_for(path, rules):
    found = []
    for _, rx, owners in rules:
        if rx.match(path):
            found = owners
    return found


def required(change_id, codeowners_path):
    route = read_json(config.RUNS / str(change_id) / "route.json") or {}
    files = route.get("files", [])
    if not files:
        return {"lane": None, "files": [], "owners": []}
    top = max(LANE_RANK.get(f["lane"], 0) for f in files)
    top_files = [f["path"] for f in files if LANE_RANK.get(f["lane"], 0) == top]
    rules = parse(open(codeowners_path, encoding="utf8").read())
    owners = []
    for p in top_files:
        for o in owners_for(p, rules):
            if o not in owners:
                owners.append(o)
    return {"lane": f"L{top}", "files": top_files, "owners": owners}
