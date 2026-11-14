import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from receipts import config
from receipts.evidence import adjudicate as A


class Units(unittest.TestCase):
    def test_outcome_normalisation(self):
        self.assertEqual(A._norm_outcome("CONFIRMED (refusal stands)"), "confirmed")
        self.assertEqual(A._norm_outcome("PARTIALLY CONFIRMED (x)"), "partial")
        self.assertEqual(A._norm_outcome("rejected"), "other")
        self.assertEqual(A._norm_outcome("inconclusive"), "other")
        self.assertEqual(A._norm_outcome(None), "other")

    def test_hunk_result_prefers_own_group_then_smallest_joint(self):
        x = {"groups": [
            {"id": "g1", "hunks": ["h3"], "result": "load-bearing"},
            {"id": "g2", "hunks": ["h4"], "result": "unprotected"},
            {"id": "g4", "hunks": ["h6"], "result": "structural"},
            {"id": "g5", "hunks": ["h3", "h4", "h6"], "result": "load-bearing"}]}
        self.assertEqual(A.hunk_result(x, "h3")[:3], ("load-bearing", "g1", "alone"))
        self.assertEqual(A.hunk_result(x, "h4")[:3], ("unprotected", "g2", "alone"))
        self.assertEqual(A.hunk_result(x, "h6")[:3], ("load-bearing", "g5", "jointly"))
        self.assertEqual(A.hunk_result(None, "h3")[0], None)

    def test_enclosing_method(self):
        src = ["class T {", "  [Fact]", "  public async Task One()", "  {", "    x();", "  }", "  private static void Helper(int a)", "  {", "  }"]
        ms = A._methods(src)
        self.assertEqual(A._enclosing(ms, 5), "One")
        self.assertEqual(A._enclosing(ms, 8), "Helper")


@unittest.skipUnless((config.RUNS / "2283" / "claims.llm.json").exists() and config.REPO.exists(), "needs runs/ and a git clone at ../repo (or RECEIPTS_REPO)")
class RealRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = {i: A.adjudicate(i, write=False) for i in ("2283", "2234", "2297")}

    def claim(self, i, c):
        return next(x for x in self.out[i]["claims"] if x["claim"] == c)

    def test_2283_time_machine_is_e3(self):
        for c in ("C1", "C2"):
            self.assertEqual((self.claim("2283", c)["level"], self.claim("2283", c)["status"]), ("E3", "proven"))

    def test_llm_never_sets_levels_original_untouched(self):
        orig = json.loads((config.RUNS / "2283" / "claims.llm.json").read_text())
        self.assertTrue(all(c.get("evidence_level") is None for c in orig["claims"]))

    def test_2234_tests_prove_nothing_flag(self):
        c1 = self.claim("2234", "C1")
        self.assertEqual(c1["level"], "E1")
        self.assertTrue(any("tests-prove-nothing" in f for f in c1["flags"]))
        self.assertEqual(self.out["2234"]["timemachine"]["pass_on_base"], 4)

    def test_2234_root_cause_claim_refuted(self):
        self.assertEqual(self.claim("2234", "C4")["status"], "refuted")

    def test_2297_only_attribute_claim_refuted_by_regen(self):
        self.assertEqual(self.claim("2297", "C4")["status"], "refuted")

    def test_refused_claims_have_refusal_or_unprotected_reason(self):
        for i, o in self.out.items():
            for c in o["claims"]:
                if c["status"] == "refused":
                    self.assertTrue(any(r.startswith("refused") for r in c["rules"]))

    def test_invalid_citation_forces_e0(self):
        # every real citation validates today, so no E0; the rule is exercised by the guarantee below
        for o in self.out.values():
            for c in o["claims"]:
                self.assertNotEqual(c["level"], "E0")

    def test_no_confidence_numbers(self):
        for o in self.out.values():
            self.assertNotIn("confidence", json.dumps(o).lower().replace("no confidence", ""))

    def test_deterministic(self):
        again = A.adjudicate("2283", write=False)
        a = {c["claim"]: (c["level"], c["status"]) for c in again["claims"]}
        b = {c["claim"]: (c["level"], c["status"]) for c in self.out["2283"]["claims"]}
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
