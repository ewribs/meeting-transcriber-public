import json
import tempfile
import unittest
from pathlib import Path

from app_settings import (
    load_app_settings,
    save_app_settings,
    update_app_setting,
)


class AppSettingsTests(unittest.TestCase):
    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            settings = load_app_settings(path)

        self.assertEqual(
            settings["performance_profile"],
            "Auto",
        )
        self.assertEqual(
            settings["execution_profile"],
            "Balanced",
        )
        self.assertEqual(
            settings["llm_model"],
            "qwen3:8b",
        )
        self.assertEqual(
            settings["llm_context_size"],
            0,
        )
        self.assertEqual(
            settings["llm_context_mode"],
            "profile_default",
        )
        self.assertEqual(
            settings["m4a_retention_days"],
            30,
        )
        self.assertEqual(
            settings["archived_m4a_retention_days"],
            365,
        )

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            save_app_settings(
                {
                    "execution_profile": "Aggressive",
                    "future_setting": "keep-me",
                },
                path,
            )
            loaded = load_app_settings(path)

        self.assertEqual(
            loaded["execution_profile"],
            "Aggressive",
        )
        self.assertEqual(
            loaded["future_setting"],
            "keep-me",
        )

    def test_update_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            save_app_settings(
                {
                    "future_setting": "keep-me",
                },
                path,
            )
            update_app_setting(
                "execution_profile",
                "Conservative",
                path,
            )
            loaded = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(
            loaded["execution_profile"],
            "Conservative",
        )
        self.assertEqual(
            loaded["future_setting"],
            "keep-me",
        )

    def test_storage_paths_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            save_app_settings(
                {
                    "output_dir": "/tmp/meeting-output",
                    "archive_dir": "/Volumes/Transcribe",
                },
                path,
            )
            loaded = load_app_settings(path)

        self.assertEqual(
            loaded["output_dir"],
            "/tmp/meeting-output",
        )
        self.assertEqual(
            loaded["archive_dir"],
            "/Volumes/Transcribe",
        )

    def test_model_and_retention_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            save_app_settings(
                {
                    "llm_model": "qwen3:14b",
                    "llm_context_size": 16384,
                    "m4a_retention_days": 45,
                    "archived_m4a_retention_days": 730,
                },
                path,
            )
            loaded = load_app_settings(path)

        self.assertEqual(
            loaded["llm_model"],
            "qwen3:14b",
        )
        self.assertEqual(
            loaded["llm_context_size"],
            16384,
        )
        self.assertEqual(
            loaded["m4a_retention_days"],
            45,
        )
        self.assertEqual(
            loaded["archived_m4a_retention_days"],
            730,
        )

    def test_legacy_execution_profile_migrates_when_new_setting_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                json.dumps({"execution_profile": "Aggressive"}),
                encoding="utf-8",
            )
            loaded = load_app_settings(path)

        self.assertEqual(
            loaded["performance_profile"],
            "High Performance",
        )

    def test_legacy_positive_context_size_migrates_to_override_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                json.dumps({"llm_context_size": 16384}),
                encoding="utf-8",
            )
            loaded = load_app_settings(path)

        self.assertEqual(loaded["llm_context_mode"], "override")
        self.assertEqual(loaded["llm_context_size"], 16384)

    def test_profile_default_mode_ignores_stale_numeric_context_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                json.dumps({
                    "llm_context_mode": "profile_default",
                    "llm_context_size": 16384,
                }),
                encoding="utf-8",
            )
            loaded = load_app_settings(path)

        self.assertEqual(loaded["llm_context_mode"], "profile_default")
        self.assertEqual(loaded["llm_context_size"], 0)

    def test_invalid_json_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                "not-json",
                encoding="utf-8",
            )
            loaded = load_app_settings(path)

        self.assertEqual(
            loaded["execution_profile"],
            "Balanced",
        )


if __name__ == "__main__":
    unittest.main()
