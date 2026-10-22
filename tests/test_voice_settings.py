import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app_settings
import backend_bridge
import voice_profiles as vp


class VoiceSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings_path = self.root / "settings.json"
        self.store_path = self.root / "profiles.json"
        self.log_path = self.root / "auto.log"
        patch = mock.patch.object(app_settings, "SETTINGS_PATH", self.settings_path)
        patch.start()
        self.addCleanup(patch.stop)

    def payload(self):
        return backend_bridge.voice_settings_payload(self.store_path, self.log_path)

    def save(self, enabled, update="on"):
        return backend_bridge.save_voice_settings_payload(
            enabled, update, self.store_path, self.log_path)

    def add_person(self):
        store = vp.VoiceStore.load(self.store_path)
        store.ensure_person("Jordan")
        store.save(self.store_path)

    def test_defaults_are_off_and_not_ready(self):
        payload = self.payload()
        self.assertFalse(payload["settings"]["enabled"])
        self.assertTrue(payload["settings"]["update_participants"])
        self.assertFalse(payload["status"]["ready"])
        self.assertIn("not set up", payload["status"]["reason"])
        self.assertEqual(payload["status"]["people_count"], 0)

    def test_cannot_turn_on_without_voice_tools(self):
        with self.assertRaises(ValueError):
            self.save("on")
        self.assertFalse(app_settings.load_app_settings()["voice_recognition_enabled"])

    def test_cannot_turn_on_without_profiles(self):
        app_settings.save_app_settings({"voice_python": "/x/python"})
        with self.assertRaises(ValueError) as caught:
            self.save("on")
        self.assertIn("fingerprinted", str(caught.exception))

    def test_turn_on_and_off(self):
        app_settings.save_app_settings({"voice_python": "/x/python"})
        self.add_person()
        payload = self.save("on", "off")
        self.assertTrue(payload["settings"]["enabled"])
        self.assertFalse(payload["settings"]["update_participants"])
        self.assertTrue(payload["status"]["ready"])
        self.assertEqual(payload["status"]["people_count"], 1)
        payload = self.save("off")
        self.assertFalse(payload["settings"]["enabled"])
        saved = json.loads(self.settings_path.read_text())
        self.assertFalse(saved["voice_recognition_enabled"])

    def test_turning_off_always_works(self):
        payload = self.save("off")
        self.assertFalse(payload["settings"]["enabled"])

    def test_other_settings_are_kept(self):
        app_settings.save_app_settings({"llm_model": "keep-me"})
        self.save("off")
        self.assertEqual(app_settings.load_app_settings()["llm_model"], "keep-me")

    def test_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            self.save("maybe")
        with self.assertRaises(ValueError):
            self.save("off", "perhaps")

    def test_recent_runs_come_from_the_log(self):
        self.log_path.write_text("one\ntwo\n", encoding="utf-8")
        self.assertEqual(self.payload()["status"]["recent"], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
