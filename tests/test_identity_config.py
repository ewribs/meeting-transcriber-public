import json
import tempfile
import unittest
from pathlib import Path

from identity_config import load_identity_config


class IdentityConfigTests(unittest.TestCase):
    def test_missing_file_uses_public_safe_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = load_identity_config(Path(temp_dir) / "missing.json")

        self.assertEqual(result["self_name"], "User")
        self.assertEqual(result["self_reference_names"], ("User",))
        self.assertEqual(result["self_speaker_label"], "Mic")
        self.assertFalse(result["configured"])

    def test_local_identity_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "identity.local.json"
            path.write_text(
                json.dumps(
                    {
                        "self_name": "Local User",
                        "self_reference_names": ["Local User", "LU"],
                        "self_speaker_label": "Mic",
                    }
                ),
                encoding="utf-8",
            )
            result = load_identity_config(path)

        self.assertEqual(result["self_name"], "Local User")
        self.assertEqual(result["self_reference_names"], ("Local User", "LU"))
        self.assertEqual(result["self_speaker_label"], "Mic")
        self.assertTrue(result["configured"])

    def test_self_name_is_injected_and_references_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "identity.local.json"
            path.write_text(
                json.dumps(
                    {
                        "self_name": "Local User",
                        "self_reference_names": ["LU", "local user", "LU"],
                    }
                ),
                encoding="utf-8",
            )
            result = load_identity_config(path)

        self.assertEqual(result["self_reference_names"], ("Local User", "LU"))

    def test_malformed_existing_file_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "identity.local.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Unable to read identity"):
                load_identity_config(path)

    def test_blank_self_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "identity.local.json"
            path.write_text(
                json.dumps({"self_name": "", "self_reference_names": []}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "self_name must not be blank"):
                load_identity_config(path)


if __name__ == "__main__":
    unittest.main()
