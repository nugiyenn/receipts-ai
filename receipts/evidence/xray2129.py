"""Hunk X-Ray for change 2129: revert each source hunk group in a head worktree and run the new tests.
Local only. Needs DOTNET_ROOT on PATH and a .NET 9 SDK (the execution tests need Roslyn 4.12).
Groups are the hunks whose revert still compiles; hunks that are only used by others are listed as structural."""
import json, os, re, subprocess, time
ROOT = "/Users/andy/Downloads/Junction2"
REPO = f"{ROOT}/repo"; WT = f"{ROOT}/wt/2129-xray"; RUN = f"{ROOT}/receipts/runs/2129"
DIAG = "FullyQualifiedName~GeneratedMessagePackFormatterTests"
EXEC = "FullyQualifiedName~GeneratedFormatterForExternalTypesTests"
BASE, HEADREF = "origin/ju26-issue-2129~1", "origin/ju26-issue-2129"
GLOBAL = '{"sdk":{"version":"9.0.100","rollForward":"latestMajor","allowPrerelease":false}}\n'
GROUPS = [
  {"id": "g1", "hunks": ["h16"], "desc": "GeneratorUtilities: hand-written formatter search skips classes marked [GeneratedMessagePackFormatter]"},
  {"id": "g2", "hunks": ["h15"], "desc": "ObjectSerializationInfo.Equals compares IsUserDeclaredFormatter"},
  {"id": "g3", "hunks": ["h20", "h22"], "desc": "FormatterTemplate.cs and StringKeyFormatterTemplate.cs emit 'partial class' for user-declared formatters (T4 output)"},
  {"id": "g4", "hunks": ["h17", "h18"], "desc": "MessagePackGenerator: collect [GeneratedMessagePackFormatter] classes and add their models"},
  {"id": "g5", "hunks": ["h19"], "desc": "MessagePackGenerator: report diagnostics for [GeneratedMessagePackFormatter] classes"},
  {"id": "g6", "hunks": ["h11"], "desc": "Analyzer SupportedDiagnostics lists the four new descriptors"},
  {"id": "g7", "hunks": ["h24"], "desc": "Constants for the attribute name and SurrogateType (used by h17, h16, h12: structural when alone)"},
  {"id": "g9", "hunks": ["h17", "h18", "h19"], "desc": "MessagePackGenerator: all three hunks together (collection, model loop, diagnostics)"},
  {"id": "g8", "hunks": ["h14"], "desc": "ObjectSerializationInfo.IsUserDeclaredFormatter property (used by templates and collector: structural when alone)"},
]
def sh(cmd, cwd, log=None):
    p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    out = p.stdout + p.stderr
    if log: open(log, "w").write(out)
    return p.returncode, out
def hunk_patches(change):
    """patch text per hunk id: file header + that hunk only, from `git diff -U3`."""
    by_path = {}
    for h in change["hunks"]:
        by_path.setdefault(h["path"], []).append(h)
    res = {}
    for path, hs in by_path.items():
        rc, d = sh(f"git diff -U3 {BASE} {HEADREF} -- '{path}'", REPO)
        head, *parts = re.split(r"(?m)^(?=@@ )", d)
        for h, part in zip(hs, parts):
            res[h["id"]] = (path, head, part)
    return res
def run_tests(wt, tag):
    out_all, failed, compiled, secs, broke_tests = "", set(), True, 0.0, set()
    for name, proj, flt in (("diag", "tests/MessagePack.SourceGenerator.Tests", DIAG), ("exec", "tests/MessagePack.SourceGenerator.ExecutionTests", EXEC)):
        t = time.time()
        rc, out = sh(f"dotnet test {proj} -f net8.0 --filter '{flt}' --logger 'console;verbosity=normal'", wt, f"{RUN}/xray/{tag}-{name}.log")
        secs += time.time() - t
        errs = re.findall(r"(\S+\.cs)\(\d+,\d+\): error (CS\d+)", out)
        if any("/src/" in f and "/obj/" not in f for f, _ in errs): compiled = False       # generator source does not build: structural
        if any(not ("/src/" in f and "/obj/" not in f) for f, _ in errs): broke_tests.add(name)   # only the test project breaks: the tests notice
        failed |= {f"{name}:{x}" for x in re.findall(r"^\s*Failed (\S+)", out, re.M)}
        out_all += out
    return compiled, sorted(failed) + sorted(f"{n}:build-broken" for n in broke_tests), round(secs, 1)
def main():
    os.makedirs(f"{RUN}/xray", exist_ok=True)
    change = json.load(open(f"{RUN}/change.json")); patches = hunk_patches(change)
    results = []
    for g in GROUPS:
        sh("git checkout -- . && git clean -fdq -e bin -e obj", WT); open(f"{WT}/global.json", "w").write(GLOBAL)
        # one patch per file, with only the group's hunks in it
        files = {}
        for hid in g["hunks"]:
            path, head, part = patches[hid]; files.setdefault(path, [head, []])[1].append(part)
        pf = f"{RUN}/xray/{g['id']}.patch"
        open(pf, "w").write("".join(h + "".join(ps) for h, ps in files.values()))
        rc, out = sh(f"git apply -R --recount '{pf}'", WT)
        if rc: results.append({**g, "result": "error", "note": out}); continue
        compiled, failed, secs = run_tests(WT, g["id"])
        res = "structural" if not compiled else ("load-bearing" if failed else "unprotected")
        results.append({**g, "result": res, "compiled": compiled, "failing_tests": failed, "seconds": secs,
                        "log": f"runs/2129/xray/{g['id']}-*.log"})
        print(g["id"], res, len(failed), secs, flush=True)
        json.dump({"change": "2129", "scope": f"revert one hunk group at a time on head; run {DIAG} (6 tests) and {EXEC} (7 tests); other suites not run",
                   "sdk": "9.0.321 (global.json overridden inside the worktree only)", "groups": results}, open(f"{RUN}/xray.json", "w"), indent=1)
    sh("git checkout -- . ", WT)
if __name__ == "__main__": main()
