"""ROUTING BACKTEST (heuristic): replay the deterministic router over real MessagePack-CSharp first-parent history
and check whether later reverts / regression fixes would have landed in light-review lanes.
LIMITS (also written into data/backtest.json): area-based routing only (no blast radius, no X-Ray, no claims, since none exist historically);
escape labels are heuristic (revert / 'regress' mentions within 90 days) = noisy lower bound; hand spot-check is NOT done unless filled in."""
import re
from datetime import datetime, timedelta

from . import config
from .ingest import area_of, classify_kind, load_areas
from .router import lane_max
from .util import git, now_iso, read_json, write_json

BRANCH = "origin/master"
WINDOW_DAYS = 90
YEARS = 2
PR_RE = re.compile(r"#(\d+)")
REGRESS_RE = re.compile(r"(?i)regress|introduced in|broke|broken by|caused by")


def classify_lane(paths, areas):
    amap = {a["name"]: a for a in areas}
    kinds = {p: classify_kind(p, set(paths)) for p in paths}
    lane, reasons = "L0", []
    for p in paths:
        a = area_of(p, areas)
        k = kinds[p]
        if k in ("generated", "template-output"):
            cand = "L1"          # no regeneration proof available historically -> not L0
        elif k in ("src", "template"):
            cand = lane_max(a["default_lane"], "L2")   # LR4: source hunks not proven protected -> at least L2
        else:
            cand = a["default_lane"]
        if a.get("ceiling"):
            cand = "L3"
        lane = lane_max(lane, cand)
    return lane, sorted({area_of(p, areas)["name"] for p in paths})


def run(write=True):
    head_date = datetime.fromisoformat(git("log", "-1", "--format=%cI", BRANCH).strip())
    since = (head_date - timedelta(days=365 * YEARS)).date().isoformat()
    _, areas = load_areas()
    raw = git("log", "--first-parent", f"--since={since}", "--format=%H%x1f%P%x1f%cI%x1f%s%x1f%b%x1e", BRANCH)
    commits = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        h, parents, date, subj, body = (rec.split("\x1f") + ["", "", "", "", ""])[:5]
        commits.append({"sha": h, "parent": parents.split()[0] if parents else None, "date": date, "subject": subj, "body": body})
    # all commits (any parent) for the escape scan
    allraw = git("log", f"--since={since}", "--format=%H%x1f%cI%x1f%s%x1f%b%x1e", BRANCH)
    allc = []
    for rec in allraw.split("\x1e"):
        rec = rec.strip("\n")
        if rec:
            h, d, s, b = (rec.split("\x1f") + ["", "", ""])[:4]
            allc.append({"sha": h, "date": datetime.fromisoformat(d), "subject": s, "msg": s + "\n" + b})

    rows = []
    for c in commits:
        if not c["parent"]:
            continue
        paths = [l.split("\t", 1)[1].split("\t")[-1] for l in git("diff", "--name-status", c["parent"], c["sha"]).splitlines() if "\t" in l]
        if not paths:
            continue
        lane, ar = classify_lane(paths, areas)
        m = PR_RE.search(c["subject"])
        pr = m.group(1) if m else None
        body_lines = [l.strip() for l in c["body"].splitlines() if l.strip() and not re.match(r"(?i)(co-authored-by|signed-off-by|\*\*full changelog)", l.strip())]
        if c["subject"].startswith("Merge pull request") and body_lines:
            title = body_lines[0]                       # PR title lives in the merge body
        else:
            title = PR_RE.sub("", c["subject"]).replace("()", "").strip()   # squash/direct commit: subject minus (#N)
        cdate = datetime.fromisoformat(c["date"])
        esc = None
        for o in allc:
            if o["sha"] == c["sha"] or not (cdate < o["date"] <= cdate + timedelta(days=WINDOW_DAYS)):
                continue
            mentions = (pr and re.search(rf"#{pr}\b", o["msg"])) or (len(title) > 12 and title[:60] in o["msg"])
            if not mentions:
                continue
            if re.search(r"(?i)\brevert", o["subject"]):
                esc = {"by": o["sha"][:9], "label": "revert", "subject": o["subject"][:90]}
                break
            if REGRESS_RE.search(o["msg"]):
                esc = {"by": o["sha"][:9], "label": "regression-mention", "subject": o["subject"][:90]}
                break
        rows.append({"sha": c["sha"][:9], "date": c["date"][:10], "pr": pr, "title": title[:90], "files": len(paths),
                     "areas": ar, "lane": lane, "escape": esc})
    conf = {l: {"changes": 0, "escapes": 0} for l in config.LANE_ORDER}
    for r in rows:
        conf[r["lane"]]["changes"] += 1
        conf[r["lane"]]["escapes"] += 1 if r["escape"] else 0
    total, esc_total = len(rows), sum(1 for r in rows if r["escape"])
    light = conf["L0"]["escapes"] + conf["L1"]["escapes"]
    interp = ("Too few labelled escapes (%d) to say anything about router recall. Treat this as DESCRIPTIVE (how changes distribute over lanes), not as evidence that light lanes are safe." % esc_total
              if esc_total < 3 else "Escapes per lane above are heuristic; see method and spot-check status.")
    out = {
        "label": "REAL public OSS history (MessagePack-CSharp, first-parent of origin/master), HEURISTIC labels",
        "generated_at": now_iso(), "window": {"since": since, "until": head_date.date().isoformat(), "escape_window_days": WINDOW_DAYS},
        "method": {"router": "areas.yaml default/ceiling lanes; source hunks >= L2 (LR4: no X-Ray historically); generated-only -> L1 (no regeneration proof)",
                   "escape_label": "later commit within 90 days mentioning the change (#PR or title) AND (subject has 'Revert' OR message has regress/introduced in/broke/caused by)",
                   "not_modelled": ["blast radius", "X-Ray", "claims/evidence", "refusals"]},
        "summary": {"changes": total, "escapes": esc_total, "escape_rate": round(esc_total / total, 4) if total else None,
                    "escapes_in_light_lanes_L0_L1": light, "escapes_in_L2_L3": esc_total - light,
                    "share_in_light_lanes": round((conf["L0"]["changes"] + conf["L1"]["changes"]) / total, 4) if total else None,
                    "share_routed_to_humans_L2_L3": round((conf["L2"]["changes"] + conf["L3"]["changes"]) / total, 4) if total else None,
                    "escape_rate_light_lanes": round(light / max(1, conf["L0"]["changes"] + conf["L1"]["changes"]), 4)},
        "interpretation": interp,
        "confusion_by_lane": conf,
        "hand_spot_check": {"required": 10, "checked": 0, "label_precision": None,
                            "status": "NOT DONE (placeholder). Do not quote label precision until a human has checked 10 labels."},
        "changes": rows,
    }
    if write:
        prev = read_json(config.DATA / "backtest.json", {}) or {}
        if "escape_cases" in prev:                    # real escape case studies live next to the heuristic scan
            out["escape_cases"] = prev["escape_cases"]
        if (prev.get("hand_spot_check") or {}).get("checked"):   # a completed hand check must survive a re-run
            out["hand_spot_check"] = prev["hand_spot_check"]
        write_json(config.DATA / "backtest.json", out)
    return out



# ======================================================================================================
# REAL ESCAPE CASES: hand-picked regressions from the MessagePack-CSharp history.
# For each, the INTRODUCING commit is routed with our deterministic router (as if it were a PR today),
# optionally Hunk X-Ray is run at that commit, and static rules R2/R6 are applied to the diff.
# Hand-picked sample: it says what our tooling would have done on four known escapes. It is not a statistic.
# ======================================================================================================
import json
import os
import subprocess
import time
from pathlib import Path

ESC_DIR = config.RUNS / "escapes"
WT_ROOT = config.ROOT.parent / "wt"

CASES = [
    {"id": "esc-2234", "title": "Analyzer silent for SuppressSourceGeneration types (issue #2234)",
     "introduced": "1a74a620369ea17fdff729b6f91262b91a2f7ed0", "intro_note": "inside PR #2106, shipped in v3.1.1",
     "fix": None, "fix_note": "no upstream fix in this clone; the early return is still on origin/master",
     "found_by": "issue #2234 ('worked in 3.1.0')", "detected": "2025-10-17",
     "sdk": "9.0.321", "test_project": "tests/MessagePack.SourceGenerator.Tests",
     "filter": "FullyQualifiedName~MsgPack00x|FullyQualifiedName~Analyzer|FullyQualifiedName~Generics|FullyQualifiedName~GenerationTests",
     "xray_files": ["src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs"]},
    {"id": "esc-2149", "title": "Analyzer stack overflow from a dropped recursion guard (issue #2149)",
     "introduced": "c012263f", "intro_note": "added an optional recursionGuard parameter; one call site never passed it",
     "fix": "4d5ff777", "fix_note": "PR #2150 'Fix stackoverflow on analyzer'",
     "found_by": "issue #2149", "detected": "2025-02-03",
     "sdk": "8.0.402", "test_project": "tests/MessagePack.SourceGenerator.Tests",
     "filter": "FullyQualifiedName~MsgPack00x|FullyQualifiedName~Generics|FullyQualifiedName~GenerationTests",
     "xray_files": ["src/MessagePack.SourceGenerator/CodeAnalysis/QualifiedNamedTypeName.cs",
                    "src/MessagePack.SourceGenerator/CodeAnalysis/QualifiedTypeName.cs",
                    "src/MessagePack.SourceGenerator/CodeAnalysis/GenericTypeParameterInfo.cs",
                    "src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs"]},
    {"id": "esc-2225", "title": "DateTimeOffset encoding change reverted because it broke tests (PR #2225, revert #2262)",
     "introduced": "50394986", "intro_note": "PR #2225 'Use UtcTicks instead of Ticks', one line, no test change",
     "fix": "ecba7969", "fix_note": "PR #2262 'Revert DateTimeOffset encoding change'",
     "found_by": "maintainer, 'broke our tests' (revert text)", "detected": "2026-05-14",
     "sdk": "9.0.321", "test_project": "tests/MessagePack.Tests",
     "filter": "FullyQualifiedName~DateTimeOffset|FullyQualifiedName~StandardClassLibraryStructFormatterTest",
     "xray_files": ["src/MessagePack/Formatters/StandardClassLibraryFormatter.cs"]},
    {"id": "esc-2300", "title": "Copilot PR's new test did not build on .NET Framework (fix PR #2300)",
     "introduced": "21f6e635", "intro_note": "PR #2287 'Fix OldSpec byte[] encoding', new test used Array.Fill",
     "fix": "ab3119e2", "fix_note": "PR #2300 'Fix build warning and Windows build break'",
     "found_by": "Windows build, found by the maintainer 44 days later", "detected": "2026-09-17",
     "sdk": None, "test_project": None, "filter": None, "xray_files": []},
]


def _full(sha):
    return git("rev-parse", sha).strip()


def _case_by_id(cid):
    return next(c for c in CASES if c["id"] == cid)


def _resolve(c):
    """The introducing sha in the notes may be abbreviated or wrong past 8 chars; always resolve from the prefix."""
    return _full(c["introduced"][:8])


def route_case(c, write=True):
    """Route the introducing commit (single-commit diff, parent..commit) with the real router, X-Ray results if present."""
    from . import ingest as ing, router
    sha = _resolve(c)
    config.BRANCHES[c["id"]] = sha
    out_dir = ESC_DIR / c["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch = config.RUNS / c["id"]                       # router/ingest expect runs/<id>; keep it empty and remove after
    existed = scratch.exists()
    try:
        res = router.route(c["id"], write=False)
        chg = ing.ingest(c["id"], write=False)
    finally:
        if not existed and scratch.exists() and not any(scratch.iterdir()):
            scratch.rmdir()
    if write:
        write_json(out_dir / "change.json", chg)
        write_json(out_dir / "route.json", res)
    return chg, res


UNIVERSAL = re.compile(r"\b(ever|never|always|every|all|any|full|fully|complete(?:ly)?|guarantee[sd]?)\b", re.I)
EMPTY_CATCH = re.compile(r"catch\s*(\([^)]*\))?\s*\{\s*\}", re.S)


def static_rules(chg):
    """Cheap deterministic stand-ins for R2 (silent suppression) and R6 (doc overclaim), plus the early-return pattern."""
    hits = []
    for h in chg["hunks"]:
        lines = h["text"].splitlines()
        added = [l[1:] for l in lines if l.startswith("+") and not l.startswith("+++")]
        removed = [l[1:] for l in lines if l.startswith("-") and not l.startswith("---")]
        if h["path"].endswith(".cs") and h["kind"] in ("src", "template"):
            if EMPTY_CATCH.search("\n".join(l[1:] for l in lines if l[:1] in "+ ")) and any(l.lstrip().startswith("catch") for l in added):
                hits.append({"rule": "R2", "hunk": h["id"], "why": "added empty catch"})
            early = [l for l in added if re.match(r"\s*return null;\s*$", l)] 
            late = [l for l in removed if re.match(r"\s*return null;\s*$", l)]
            if early and not late:
                hits.append({"rule": "R2-early-return", "hunk": h["id"], "why": "added an early 'return null;' that skips the rest of the method"})
            elif early and late:
                hits.append({"rule": "R2-early-return", "hunk": h["id"], "why": "moved a 'return null;' earlier: everything after it is skipped for that case"})
        if h["path"].endswith(".md"):
            u = sorted({m.group(0).lower() for l in added for m in UNIVERSAL.finditer(l)})
            if u:
                hits.append({"rule": "R6", "hunk": h["id"], "why": f"universal-claim words in added docs: {u}"})
    return hits


def _sh(cmd, cwd, log=None, env=None, timeout=1800):
    p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, env=env, timeout=timeout)
    out = p.stdout + p.stderr
    if log:
        Path(log).write_text(out)
    return p.returncode, out


def _dotnet_env():
    e = dict(os.environ)
    e["DOTNET_ROOT"] = str(Path.home() / ".dotnet")
    e["PATH"] = f"{e['DOTNET_ROOT']}:{e['PATH']}"
    e["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    e["DOTNET_NOLOGO"] = "1"
    return e


def xray_case(c, max_minutes=22):
    """Hunk X-Ray at the introducing commit: revert each src hunk alone, run the tests that existed in that commit."""
    if not c.get("test_project"):
        return None
    from .ingest import parse_diff
    sha = _resolve(c)
    out_dir = ESC_DIR / c["id"]
    (out_dir / "xray").mkdir(parents=True, exist_ok=True)
    wt = WT_ROOT / f"{c['id']}-head"
    if wt.exists():
        _sh(f"git worktree remove --force {wt}", config.REPO)
    _sh(f"git worktree add --detach {wt} {sha}", config.REPO)
    gj = wt / "global.json"                                # old pins would not accept the installed SDK band
    gj.write_text(json.dumps({"sdk": {"version": c["sdk"], "rollForward": "latestFeature", "allowPrerelease": False}}))
    env = _dotnet_env()
    t0 = time.time()
    flt = c["filter"]
    base_cmd = f"dotnet test {c['test_project']} --filter '{flt}' -v q --nologo"
    rc, out = _sh(base_cmd, wt, out_dir / "xray" / "baseline.log", env)
    base_secs = round(time.time() - t0)
    total = (re.findall(r"Total:\s+(\d+)", out) or [None])[-1]
    passed = (re.findall(r"Passed:\s+(\d+)", out) or [None])[-1]
    nfail = (re.findall(r"Failed:\s+(\d+)", out) or [None])[-1]
    failed_base = sorted(set(re.findall(r"^\s*Failed (\S+)", out, re.M)) | set(re.findall(r"^\s*(?:\[xUnit\.net [0-9:.]+\]\s+)?(\S+) \[FAIL\]", out, re.M)))
    res = {"commit": sha, "test_project": c["test_project"], "filter": flt,
           "baseline": {"exit": rc, "total": total, "passed": passed, "failed_count": nfail, "failed": failed_base, "seconds": base_secs},
           "groups": [], "scope_note": "Only the tests selected by the filter were run."}
    if not total:
        res["status"] = "baseline did not build or run; X-Ray not performed"
        write_json(out_dir / "xray.json", res)
        _sh(f"git worktree remove --force {wt}", config.REPO)
        return res
    if failed_base:                                        # does the same test set fail at the parent? (environment vs introduced)
        pw = WT_ROOT / f"{c['id']}-parent"
        if pw.exists():
            _sh(f"git worktree remove --force {pw}", config.REPO)
        _sh(f"git worktree add --detach {pw} {sha}~1", config.REPO)
        (pw / "global.json").write_text(gj.read_text())
        rcp, outp = _sh(base_cmd, pw, out_dir / "xray" / "parent-baseline.log", env)
        pfail = sorted(set(re.findall(r"^\s*(?:\[xUnit\.net [0-9:.]+\]\s+)?(\S+) \[FAIL\]", outp, re.M)))
        res["parent_baseline"] = {"exit": rcp, "total": (re.findall(r"Total:\s+(\d+)", outp) or [None])[-1],
                                  "failed": pfail, "failed_only_at_introducing_commit": sorted(set(failed_base) - set(pfail))}
        _sh(f"git worktree remove --force {pw}", config.REPO)
    # per-hunk reverse patches
    diff = git("diff", "--no-color", "-U3", f"{sha}~1", sha, "--", *c["xray_files"])
    parts = re.split(r"(?m)^(?=diff --git )", diff)
    n = 0
    for part in parts:
        if not part.strip():
            continue
        head, *hs = re.split(r"(?m)^(?=@@ )", part)
        for h in hs:
            n += 1
            gid = f"g{n}"
            patch = head + h
            pf = out_dir / "xray" / f"{gid}.patch"
            pf.write_text(patch)
            if (time.time() - t0) / 60 > max_minutes:
                res["groups"].append({"id": gid, "result": "not run (time box)", "lines": h.count("\n")})
                continue
            rc2, o2 = _sh(f"git apply -R --whitespace=nowarn {pf}", wt)
            if rc2 != 0:
                res["groups"].append({"id": gid, "result": "patch did not reverse-apply", "lines": h.count("\n")})
                continue
            t1 = time.time()
            rc3, o3 = _sh(base_cmd, wt, out_dir / "xray" / f"{gid}.log", env)
            compiled = not re.search(r"\.cs\(\d+,\d+\): error CS", o3)
            failed = sorted((set(re.findall(r"^\s*Failed (\S+)", o3, re.M)) | set(re.findall(r"^\s*(?:\[xUnit\.net [0-9:.]+\]\s+)?(\S+) \[FAIL\]", o3, re.M))) - set(failed_base))
            ran = bool(re.search(r"Total:\s+\d+", o3))
            harness_err = "compatible .NET SDK was not found" in o3
            crashed = compiled and not harness_err and "Test Run Aborted" in o3
            if crashed and not failed:
                failed = ["(test host aborted: " + ("stack overflow" if "Stack overflow" in o3 or "StackOverflow" in o3 else "crash") + ")"]
            fixed = sorted(set(failed_base) - set(re.findall(r"^\s*(?:\[xUnit\.net [0-9:.]+\]\s+)?(\S+) \[FAIL\]", o3, re.M))) if failed_base and ran else []
            result = "harness error" if harness_err else ("breaks-existing-test" if (fixed and compiled and not failed and not set(fixed) <= set(res.get("parent_baseline", {}).get("failed", []))) else None) or ("structural" if not compiled else ("load-bearing" if failed else "unprotected"))
            res["groups"].append({"id": gid, "file": re.findall(r"\+\+\+ b/(\S+)", head)[0] if re.findall(r"\+\+\+ b/(\S+)", head) else None,
                                  "header": h.splitlines()[0][:80], "result": result, "compiled": compiled,
                                  "failing_tests": failed, "fixed_by_revert": sorted(set(failed_base) - set(re.findall(r"^\s*(?:\[xUnit\.net [0-9:.]+\]\s+)?(\S+) \[FAIL\]", o3, re.M))) if failed_base and ran else [],
                                  "seconds": round(time.time() - t1), "lines": h.count("\n")})
            _sh("git checkout -- " + " ".join(c["xray_files"]), wt)   # restore only the source files (global.json stays patched)
            write_json(out_dir / "xray.json", res)
    res["total_seconds"] = round(time.time() - t0)
    write_json(out_dir / "xray.json", res)
    _sh(f"git worktree remove --force {wt}", config.REPO)
    return res


VERDICTS = {
    "esc-2234": {
        "defect": "TypeCollector.cs: the new early 'return null' (hunk 2 of the commit) skips the collection the analyzer relies on for SuppressSourceGeneration types.",
        "pointed_at_defect": "yes",
        "why": "X-Ray at the commit: both source hunks are unprotected, no passing test fails when either is reverted. The R2-early-return pattern also fires on the moved 'return null'. That pattern was written after reading this commit, so it is hindsight, not recall.",
        "human_asked": "Nothing tests this early return. Every check after it is skipped for suppressed types. Is that intended?",
        "limits": "9 of 103 tests in the selected set fail on this machine at the parent commit too (same 9), so they gave no signal. Router budget of 185 lines includes 170 lines of sandbox/Program.cs that our area map counts as source; the real source change is 15 lines.",
    },
    "esc-2149": {
        "defect": "A call site that was never touched by the commit (target-typed 'new(nesting)' in QualifiedNamedTypeName.cs) kept using the default recursionGuard = null.",
        "pointed_at_defect": "no",
        "why": "Every logic hunk in the commit is protected (reverting the guard pass-through crashes the test host with a stack overflow) or structural. The three unprotected hunks only remove 'using' lines. The defect is in code the diff does not contain, which X-Ray cannot see. Blast radius (QualifiedNamedTypeName has 48 references) keeps the lane at L2, but that comes from reference counts, not from the defect.",
        "human_asked": "A reviewer is asked to read 10 flagged hunks. Nothing points at the untouched call site.",
        "limits": "A grep for call sites cannot find target-typed 'new(...)' expressions. Finding the missed call site needs a semantic tool such as Roslyn or an IDE find-usages.",
    },
    "esc-2225": {
        "defect": "StandardClassLibraryFormatter.cs: Ticks became UtcTicks, which changes the bytes written for DateTimeOffset (wire format) and broke an existing test.",
        "pointed_at_defect": "yes",
        "why": "The commit touches the runtime-serializer ceiling area, so the lane is L3 and a human reads the whole 2-line change, which comes with no test change. On this machine (Europe/Helsinki) the existing DateTimeOffsetTest fails at the commit and passes at its parent. With TZ=UTC all 8 selected tests pass, so a UTC CI runner would have stayed green.",
        "human_asked": "Full read of 2 lines in a serializer. Does a different tick value change the encoded bytes for existing data?",
        "limits": "Router lane comes from the area ceiling, not from understanding wire formats. Whether a reviewer sees the compatibility problem is the reviewer's call; we only guarantee they are asked.",
    },
    "esc-2300": {
        "defect": "tests/MessagePack.Tests/MessagePackWriterTests.cs: new test calls Array.Fill, which does not exist on .NET Framework 4.7.2, so Windows builds broke.",
        "pointed_at_defect": "no machine evidence",
        "why": "Lane is L3 by the ceiling area, so a human reads all 97 changed lines including the Array.Fill line. Our execution evidence runs on net8/net9 on macOS, where the line compiles and passes, so nothing we run would have shown the break. It needs a Windows runner or a reviewer who knows the net472 target.",
        "human_asked": "Full read of 97 lines. No specific question about target frameworks.",
        "limits": "X-Ray was not run for this case: the defect is a compile break on a target we cannot build here.",
    },
}


def escape_cases(do_xray=False, write=True):
    rows = []
    for c in CASES:
        chg, rt = route_case(c)
        sha = _resolve(c)
        stat = static_rules(chg)
        xr = read_json(ESC_DIR / c["id"] / "xray.json")
        d_intro = git("log", "-1", "--format=%cI", sha).strip()[:10]
        d_fix = git("log", "-1", "--format=%cI", _full(c["fix"])).strip()[:10] if c["fix"] else None
        rows.append({
            "id": c["id"], "title": c["title"], "introducing_commit": sha[:8], "introduced_on": d_intro,
            "introducing_note": c["intro_note"], "fix_commit": c["fix"], "fixed_on": d_fix, "fix_note": c["fix_note"],
            "found_by": c["found_by"], "detected_on": c["detected"],
            "days_to_detection": (datetime.fromisoformat(c["detected"]) - datetime.fromisoformat(d_intro)).days,
            "files": chg["totals"]["files"], "changed_lines": chg["totals"]["changed_lines"],
            "areas": rt["areas"], "lane": rt["lane"], "lane_reasons": [r["why"] for r in rt["reasons"]],
            "blast_radius": {"symbol": rt["blast_radius"]["top_symbol"], "references": rt["blast_radius"]["max_references"]},
            "light_lane": rt["lane"] in ("L0", "L1"),
            "static_rules": stat,
            "reading_budget_router": {"lines": rt["reading_budget"]["lines"], "of": rt["reading_budget"]["total_changed_lines"], "note": "no X-Ray folded in: the router sees only the baseline files in runs/escapes/<id>/"},
            "verdict": VERDICTS[c["id"]],
            "xray": None if not xr else {"scope": xr.get("scope_note"), "baseline": xr.get("baseline"),
                                          "groups": [{k: g.get(k) for k in ("id", "file", "result", "failing_tests", "lines")} for g in xr.get("groups", [])]},
        })
    heavy = sum(1 for r in rows if not r["light_lane"])
    pointed = sum(1 for r in rows if r["verdict"]["pointed_at_defect"] == "yes")
    out = {"label": "REAL escapes from MessagePack-CSharp history, hand-picked sample (n=%d). Not a statistic." % len(rows),
           "pointed_at_defect_by_evidence": {"yes": pointed, "no": sum(1 for r in rows if r["verdict"]["pointed_at_defect"] == "no"),
                                              "no_machine_evidence": sum(1 for r in rows if r["verdict"]["pointed_at_defect"] == "no machine evidence")},
           "generated_at": now_iso(), "cases": rows,
           "confusion": {"light_lanes_L0_L1": len(rows) - heavy, "heavy_lanes_L2_L3": heavy, "n": len(rows)},
           "method": "Router run on the introducing commit as a single-commit change (parent..commit), same code as for the ju26 changes; "
                     "no claims or refusals existed, so lane comes from areas, ceiling, blast radius and (where run) X-Ray."}
    if write:
        bt = read_json(config.DATA / "backtest.json", {}) or {}
        bt["escape_cases"] = out
        write_json(config.DATA / "backtest.json", bt)
    return out


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cases"
    if cmd == "xray":
        print(json.dumps({g["id"]: g["result"] for g in (xray_case(_case_by_id(sys.argv[2])) or {"groups": []})["groups"]}))
    else:
        r = escape_cases()
        for x in r["cases"]:
            print(x["id"], x["lane"], x["areas"], x["blast_radius"], [s["rule"] for s in x["static_rules"]])
