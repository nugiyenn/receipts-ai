import json, sys
sys.path.insert(0, "/Users/andy/Downloads/Junction2/receipts")
from receipts.evidence import xray2129 as X
import os, re
data = json.load(open(X.RUN + "/xray.json"))
# reclassify existing groups from saved logs with the corrected rule, then run g9
for g in data["groups"]:
    failed, compiled, broke = set(), True, set()
    for name in ("diag", "exec"):
        out = open(f"{X.RUN}/xray/{g['id']}-{name}.log").read()
        errs = re.findall(r"(\S+\.cs)\(\d+,\d+\): error (CS\d+)", out)
        if any("/src/" in f and "/obj/" not in f for f, _ in errs): compiled = False
        if any(not ("/src/" in f and "/obj/" not in f) for f, _ in errs): broke.add(name)
        failed |= {f"{name}:{x}" for x in re.findall(r"^\s*Failed (\S+)", out, re.M)}
    g["compiled"] = compiled
    g["failing_tests"] = sorted(failed) + sorted(f"{n}:build-broken" for n in broke)
    g["result"] = "structural" if not compiled else ("load-bearing" if g["failing_tests"] else "unprotected")
json.dump(data, open(X.RUN + "/xray.json", "w"), indent=1)
print([(g["id"], g["result"]) for g in data["groups"]])
