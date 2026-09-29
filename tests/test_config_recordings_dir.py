import unittest
from pathlib import Path


class ConfigRecordingsDirTests(unittest.TestCase):
    def test_config_uses_recordings_dir_setting(self):
        text = Path("config.py").read_text(encoding="utf-8")
        self.assertIn(
            '_APP_SETTINGS.get("recordings_dir")',
            text,
        )

    def test_config_preserves_legacy_meetings_fallback(self):
        text = Path("config.py").read_text(encoding="utf-8")
        self.assertIn(
            'or (PROJECT_DIR / "meetings")',
            text,
        )


if __name__ == "__main__":
    unittest.main()
