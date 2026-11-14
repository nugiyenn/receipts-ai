import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from receipts import config, ingest, ledger, receipt, citations, router
from receipts.util import glob_to_regex

DIFF = """diff --git a/src/A.cs b/src/A.cs
index 1..2 100644
--- a/src/A.cs
+++ b/src/A.cs
@@ -10,2 +10,3 @@ class A
 x
-y
+z
+w
diff --git a/tests/T.cs b/tests/T.cs
new file mode 100644
--- /dev/null
+++ b/tests/T.cs
@@ -0,0 +1,2 @@
+a
+b
"""


class T(unittest.TestCase):
    def test_glob(self):
        self.assertTrue(glob_to_regex("**/*.g.cs").match("a/b/c.g.cs"))
        self.assertTrue(glob_to_regex("**/*.g.cs").match("c.g.cs"))
        self.assertTrue(glob_to_regex("src/MessagePack/**").match("src/MessagePack/x/y.cs"))
        self.assertFalse(glob_to_regex("src/MessagePack/**").match("src/MessagePack.SourceGenerator/x.cs"))

    def test_parse_diff(self):
        f = ingest.parse_diff(DIFF)
        self.assertEqual([x["b"] for x in f], ["src/A.cs", "tests/T.cs"])
        h = f[0]["hunks"][0]
        self.assertEqual((h["old_start"], h["new_start"], h["new_len"], h["added"], h["removed"]), (10, 10, 3, 2, 1))
        self.assertEqual(f[1]["status"], "added")

    def test_kinds(self):
        self.assertEqual(ingest.classify_kind("x/Resources/a.cs", set()), "generated")
        self.assertEqual(ingest.classify_kind("a/T.cs", {"a/T.tt", "a/T.cs"}), "template-output")
        self.assertEqual(ingest.classify_kind("README.md", set()), "doc")

    def test_ledger_rules(self):
        promo, demo, cold = ledger.params()
        cfg = ledger.area_cfgs()["analyzer-core"]
        st = ledger.new_state(cfg, cold)
        rec = lambda **k: {**dict(receipts=7, escapes=0, canary_planted=4, canary_caught=4, changed_lines=1, routed_lines=0, routed_changes=0,
                                  findings=0, findings_accepted=0, reverts=0, median_review_min=1, median_ttm_h=1), **k}
        for w in (1, 2, 3):
            ledger.step(st, w, rec(), cfg, promo, demo)
        self.assertEqual(st["lane"], "L1")                      # 21 clean + recall 100% -> promoted
        ledger.step(st, 4, rec(escapes=1), cfg, promo, demo)
        self.assertEqual(st["lane"], "L3")                      # any escape -> immediate demotion
        ledger.step(st, 5, rec(), cfg, promo, demo)
        self.assertEqual(st["lane"], "L2")                      # 10+ clean after escape
        rt = ledger.area_cfgs()["runtime-serializer"]
        s2 = ledger.new_state(rt, cold)
        for w in range(1, 8):
            ledger.step(s2, w, rec(), rt, promo, demo)
        self.assertEqual(s2["lane"], "L3")                      # ceiling areas never promote

    def test_own_words_guard(self):
        run = Path(tempfile.mkdtemp())
        (run / "claims.json").write_text(json.dumps({"claims": [{"text": "the analyzer does not crash for closed generic value types from referenced assemblies"}]}))
        ok, msg, _ = receipt.own_words_guard("too short", run)
        self.assertFalse(ok)
        ok, msg, ov = receipt.own_words_guard("the analyzer does not crash for closed generic value types from referenced assemblies and more words here", run)
        self.assertFalse(ok, msg)
        ok, msg, ov = receipt.own_words_guard("I accept that third party libraries compiled without the analyzer stay silent and I will chase that up with the platform team next sprint", run)
        self.assertTrue(ok, msg)

    def test_citation_norm(self):
        self.assertEqual(citations.norm("  a \t b  "), "a b")


if __name__ == "__main__":
    unittest.main()
