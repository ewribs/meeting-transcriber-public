import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import private_terms as pt


class PrivateTermsTests(unittest.TestCase):
    NAMES = ["2026-01-02_0900_AlphaTeamSyncJordanX010226", "Zeta1v1010226.m4a", ".hidden"]

    def test_derive_terms_skips_dates_digits_and_generic_words(self):
        terms = pt.derive_terms(self.NAMES)
        self.assertIn("alpha", terms)
        self.assertIn("jordan", terms)
        self.assertIn("alphateamsyncjordanx", terms)
        self.assertNotIn("sync", terms)      # generic word
        self.assertFalse(any("hidden" in t for t in terms))  # dotfiles skipped
        self.assertNotIn("1v1", terms)       # contains digits / too short
        self.assertFalse(any(t.startswith("2026") for t in terms))

    def test_matcher_uses_whole_words_and_camel_case(self):
        m = pt.build_matcher({"zorkon", "alpha"})
        self.assertIsNone(pt.find_term(m, "a zorkonian token"))   # a term inside a longer word is fine
        self.assertEqual(pt.find_term(m, "meet with Zorkon today"), "zorkon")
        self.assertEqual(pt.find_term(m, "alpha_review_deck"), "alpha")
        self.assertEqual(pt.find_term(m, "AlphaReviewDeck"), "alpha")
        self.assertIsNone(pt.find_term(None, "anything"))

    def test_local_names_reads_folders_and_skips_files_in_benchmarks(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "output" / "RunOne").mkdir(parents=True)
            (d / "private_benchmarks" / "case-x").mkdir(parents=True)
            (d / "private_benchmarks" / "notes.txt").write_text("x")
            names = pt.local_names(d)
            self.assertIn("RunOne", names)
            self.assertIn("case-x", names)
            self.assertNotIn("notes.txt", names)


if __name__ == "__main__":
    unittest.main()
