import json, sys
sys.path.insert(0, "/Users/andy/Downloads/Junction2/receipts")
from receipts.evidence import xray2129 as X
g = [x for x in X.GROUPS if x["id"] == "g9"][0]
change = json.load(open(X.RUN + "/change.json")); patches = X.hunk_patches(change)
X.sh("git checkout -- . && git clean -fdq -e bin -e obj", X.WT); open(X.WT + "/global.json", "w").write(X.GLOBAL)
files = {}
for hid in g["hunks"]:
    path, head, part = patches[hid]; files.setdefault(path, [head, []])[1].append(part)
pf = f"{X.RUN}/xray/g9.patch"; open(pf, "w").write("".join(h + "".join(ps) for h, ps in files.values()))
rc, out = X.sh(f"git apply -R --recount '{pf}'", X.WT); print("apply rc", rc, out[:200])
compiled, failed, secs = X.run_tests(X.WT, "g9")
res = "structural" if not compiled else ("load-bearing" if failed else "unprotected")
data = json.load(open(X.RUN + "/xray.json"))
data["groups"] = [x for x in data["groups"] if x["id"] != "g9"] + [{**g, "result": res, "compiled": compiled, "failing_tests": failed, "seconds": secs, "log": "runs/2129/xray/g9-*.log"}]
json.dump(data, open(X.RUN + "/xray.json", "w"), indent=1)
X.sh("git checkout -- .", X.WT)
print("g9", res, failed, secs)
