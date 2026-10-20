import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import audit_words, release_audit


class AuditWordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "release_audit.local.json"

    def write_config(self, text):
        self.config.write_text(text, encoding="utf-8")

    def test_invalid_json_gives_plain_message(self):
        self.write_config('{"derived_allow": ["a"\n "b"]}')
        with self.assertRaises(audit_words.ConfigError) as ctx:
            audit_words.load_config(self.config)
        self.assertIn("missing comma", str(ctx.exception))

    def test_wrong_type_is_rejected(self):
        self.write_config('{"derived_allow": "help"}')
        with self.assertRaises(audit_words.ConfigError):
            audit_words.load_config(self.config)

    def test_allow_adds_sorted_lowercase_and_keeps_other_keys(self):
        self.write_config(json.dumps({
            "sensitive_literals": ["x"],
            "derived_allow": ["zebra"],
        }))
        added = audit_words.allow_words(self.config, ["Help", "  apple ", "zebra"])
        self.assertEqual(added, ["apple", "help"])
        data = json.loads(self.config.read_text())
        self.assertEqual(data["derived_allow"], ["apple", "help", "zebra"])
        self.assertEqual(data["sensitive_literals"], ["x"])
        self.assertTrue(self.config.with_name(self.config.name + ".bak").exists())

    def test_allow_creates_missing_config(self):
        audit_words.allow_words(self.config, ["help"])
        self.assertEqual(json.loads(self.config.read_text())["derived_allow"], ["help"])

    def test_nothing_new_leaves_file_untouched(self):
        self.write_config(json.dumps({"derived_allow": ["help"]}))
        before = self.config.read_text()
        self.assertEqual(audit_words.allow_words(self.config, ["help"]), [])
        self.assertEqual(self.config.read_text(), before)

    def test_hits_are_grouped_from_audit_findings(self):
        (self.root / "notes.md").write_text("one\nplease help me\n")
        findings = [
            release_audit.Finding("ERROR", "private-name-derived", "notes.md", 2,
                                  "contains a term taken from a meeting/file name ('help')"),
            release_audit.Finding("ERROR", "private-name-derived", "help.py", None,
                                  "file path contains a term taken from a meeting/file name ('help')"),
            release_audit.Finding("WARN", "xcode-development-team", "x.pbxproj", 1, "x ('team')"),
        ]
        hits = audit_words.hits_from_findings(findings, self.root)
        self.assertEqual(list(hits), ["help"])
        self.assertEqual(hits["help"][0], ("notes.md", 2, "please help me"))
        self.assertEqual(hits["help"][1][2], "(file name)")

    def test_review_allows_only_approved_words(self):
        answers = iter(["y", "n"])
        fake = {"alpha": [("a.md", 1, "alpha")], "beta": [("b.md", 2, "beta")]}
        output = []
        with patch.object(audit_words, "flagged", return_value=fake):
            audit_words.review(
                self.root, self.config,
                input_fn=lambda prompt: next(answers),
                output=output.append,
            )
        self.assertEqual(json.loads(self.config.read_text())["derived_allow"], ["alpha"])
        self.assertTrue(any("beta" in line for line in output))

    def test_review_quit_saves_earlier_answers(self):
        answers = iter(["y", "q"])
        fake = {"alpha": [("a.md", 1, "x")], "beta": [("b.md", 2, "y")], "gamma": [("c.md", 3, "z")]}
        with patch.object(audit_words, "flagged", return_value=fake):
            audit_words.review(
                self.root, self.config,
                input_fn=lambda prompt: next(answers),
                output=lambda line: None,
            )
        self.assertEqual(json.loads(self.config.read_text())["derived_allow"], ["alpha"])


if __name__ == "__main__":
    unittest.main()
