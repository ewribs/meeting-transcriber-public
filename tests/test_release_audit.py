import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import release_audit


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, rel, text=""):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_path_audit_rejects_private_config_media_and_xcuserdata(self):
        files = [
            self._write("identity.local.json", "{}"),
            self._write("sample.m4a", "x"),
            self._write("App.xcodeproj/xcuserdata/user.xcuserdatad/state.plist", "x"),
        ]
        with patch.object(release_audit, "ROOT", self.root):
            findings = release_audit.audit_paths(files)
        self.assertEqual({f.code for f in findings}, {"private-file-tracked", "media-artifact", "xcode-user-state"})

    def test_text_audit_detects_email_user_path_and_private_literal(self):
        path = self._write(
            "sample.md",
            "Owner: person" + "@example.com\n" + "Path: /" + "Users/private/Documents\n" + "Supplier: Secret Vendor\n",
        )
        config = {"sensitive_literals": ["Secret Vendor"], "allowed_bundle_prefixes": ["com.example."]}
        with patch.object(release_audit, "ROOT", self.root):
            findings = release_audit.audit_text(path, config)
        self.assertEqual({f.code for f in findings}, {"email-address", "absolute-user-path", "private-denylist"})

    def test_bundle_identifier_is_warning_not_error(self):
        path = self._write("project.pbxproj", 'PRODUCT_BUNDLE_IDENTIFIER = "com.' + 'personal.App\";\n')
        config = {"sensitive_literals": [], "allowed_bundle_prefixes": ["com.example."]}
        with patch.object(release_audit, "ROOT", self.root):
            findings = release_audit.audit_text(path, config)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "WARN")
        self.assertEqual(findings[0].code, "bundle-identifier-review")

    def test_example_bundle_identifier_is_allowed(self):
        path = self._write("project.pbxproj", 'PRODUCT_BUNDLE_IDENTIFIER = "com.example.App";\n')
        config = {"sensitive_literals": [], "allowed_bundle_prefixes": ["com.example."]}
        with patch.object(release_audit, "ROOT", self.root):
            findings = release_audit.audit_text(path, config)
        self.assertEqual(findings, [])

    def test_private_config_loader_uses_public_safe_defaults_when_missing(self):
        config = release_audit.load_private_config(self.root / "missing.json")
        self.assertEqual(config["sensitive_literals"], [])
        self.assertIn("com.example.", config["allowed_bundle_prefixes"])

    def test_private_config_loader_reads_literals(self):
        path = self._write(
            "release_audit.local.json",
            json.dumps({"sensitive_literals": ["Secret Name"], "allowed_bundle_prefixes": ["com.example."]}),
        )
        config = release_audit.load_private_config(path)
        self.assertEqual(config["sensitive_literals"], ["Secret Name"])


if __name__ == "__main__":
    unittest.main()
