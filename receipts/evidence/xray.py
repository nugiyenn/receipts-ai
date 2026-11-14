"""Hunk X-Ray for change 2283: revert each src hunk group in a head worktree, run targeted tests.
Local only. Usage: python xray.py   (expects wt/2283-head and DOTNET_ROOT on PATH)."""
import json, os, re, subprocess, sys, time, shutil
ROOT = "/Users/andy/Downloads/Junction2"
REPO = f"{ROOT}/repo"; WT = f"{ROOT}/wt"; RUN = f"{ROOT}/receipts/runs/2283"
FILTER = ("FullyQualifiedName~GenericsFormatterTests|FullyQualifiedName~MsgPack00xAnalyzerTests|"
          "FullyQualifiedName~MsgPack011|FullyQualifiedName~MsgPack012|FullyQualifiedName~MsgPack015")
SRC = "src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs"
# hunk ids match runs/2283/change.json: h3..h6 are the TypeCollector.cs hunks in diff order
GROUPS = [
  {"id": "g1", "hunks": ["h3"], "desc": "constructor wraps reportDiagnostic with ReportIfLocatedInCompilation filter"},
  {"id": "g2", "hunks": ["h4"], "desc": "BothStringAndIntKeyAreNull uses null-safe GetPropertyIdentifierLocation"},
  {"id": "g3", "hunks": ["h5"], "desc": "MemberNeedsKey uses FirstOrDefault() instead of [0]"},
  {"id": "g4", "hunks": ["h6"], "desc": "adds helper methods (alone: structural, other hunks call them)"},
  {"id": "g5", "hunks": ["h3", "h4", "h6"], "desc": "filter + property-location helper + helpers together (structural bundle)"},
]
def sh(cmd, cwd, log=None):
    p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    out = p.stdout + p.stderr
    if log: open(log, "w").write(out)
    return p.returncode, out
def hunk_patches():
    rc, d = sh(f"git diff -U3 origin/ju26-issue-2283~1 origin/ju26-issue-2283 -- {SRC}", REPO)
    head, *hs = re.split(r"(?m)^(?=@@ )", d)
    return head, hs  # hs order = h3,h4,h5,h6
def reclassify():
    """Re-derive results from saved logs (fixes the first-run classifier that matched xUnit diagnostic text)."""
    data = json.load(open(f"{RUN}/xray.json"))
    for g in data["groups"]:
        out = open(f"{RUN}/xray/{g['id']}.log").read()
        compiled = not re.search(r"\.cs\(\d+,\d+\): error CS", out)
        failed = sorted(set(re.findall(r"^\s*Failed (\S+)", out, re.M)))
        g["failing_tests"] = failed
        g["result"] = "structural" if not compiled else ("load-bearing" if failed else "unprotected")
        g["compiled"] = compiled
        g["tests_total"] = (re.findall(r"Total tests: (\d+)", out) or [None])[-1]
    json.dump(data, open(f"{RUN}/xray.json", "w"), indent=1)

def main():
    os.makedirs(f"{RUN}/xray", exist_ok=True)
    head, hs = hunk_patches(); hid = {"h3": hs[0], "h4": hs[1], "h5": hs[2], "h6": hs[3]}
    results = []
    for g in GROUPS:
        wt = f"{WT}/2283-xray-{g['id']}"
        if os.path.exists(wt): sh(f"git worktree remove --force {wt}", REPO)
        sh(f"git worktree add --detach {wt} origin/ju26-issue-2283", REPO)
        patch = head + "".join(hid[h] for h in g["hunks"])
        open(f"{RUN}/xray/{g['id']}.patch", "w").write(patch)
        rc, out = sh(f"git apply -R --recount {RUN}/xray/{g['id']}.patch", wt)
        if rc: results.append({**g, "result": "error", "note": out}); continue
        log = f"{RUN}/xray/{g['id']}.log"; t = time.time()
        rc, out = sh(f"dotnet test tests/MessagePack.SourceGenerator.Tests -f net8.0 --filter '{FILTER}' --logger 'console;verbosity=normal'", wt, log)
        secs = round(time.time() - t, 1)
        compiled = not re.search(r"\.cs\(\d+,\d+\): error CS", out)
        failed = sorted(set(re.findall(r"^\s*Failed (\S+)", out, re.M)))
        m = re.search(r"Failed:\s+(\d+).*?Passed:\s+(\d+)", out) or re.search(r"Passed!|Failed!", out)
        if not compiled: res = "structural"
        elif failed: res = "load-bearing"
        else: res = "unprotected"
        results.append({**g, "result": res, "failing_tests": failed, "seconds": secs, "log": f"runs/2283/xray/{g['id']}.log", "summary_line": (re.findall(r"(?m)^(?:Passed!|Failed!).*$", out) or [""])[-1]})
        json.dump({"filter": FILTER, "groups": results}, open(f"{RUN}/xray.json", "w"), indent=1)
        sh(f"git worktree remove --force {wt}", REPO)
    json.dump({"filter": FILTER, "groups": results}, open(f"{RUN}/xray.json", "w"), indent=1)
if __name__ == "__main__": reclassify() if "--reclassify" in sys.argv else main()
