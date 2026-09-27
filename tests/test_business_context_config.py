import json
import tempfile
import unittest
from pathlib import Path

from business_context_config import load_business_context_config


class BusinessContextConfigTests(unittest.TestCase):
    def test_missing_file_uses_public_safe_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = load_business_context_config(Path(tmp) / "missing.json")
        self.assertFalse(result["configured"])
        self.assertEqual(result["topic_normalization_rules"], ())

    def test_local_rules_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "business_context.local.json"
            path.write_text(
                json.dumps(
                    {
                        "topic_normalization_rules": [
                            {
                                "key": "vendor_alpha_renewal",
                                "markers": ["Vendor Alpha", "Alpha Renewal", "vendor alpha"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = load_business_context_config(path)

        self.assertTrue(result["configured"])
        self.assertEqual(
            result["topic_normalization_rules"],
            (("vendor_alpha_renewal", ("vendor alpha", "alpha renewal")),),
        )

    def test_invalid_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "business_context.local.json"
            path.write_text(
                json.dumps(
                    {
                        "topic_normalization_rules": [
                            {"key": "Not Safe", "markers": ["example"]}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_business_context_config(path)

    def test_empty_markers_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "business_context.local.json"
            path.write_text(
                json.dumps(
                    {
                        "topic_normalization_rules": [
                            {"key": "vendor_alpha", "markers": []}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_business_context_config(path)


if __name__ == "__main__":
    unittest.main()
