import json
import tempfile
import unittest
from pathlib import Path

from install_config import load_install_config, save_install_config


class InstallConfigTests(unittest.TestCase):
    def test_missing_install_config_returns_empty_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "install.json"
            loaded = load_install_config(path)

        self.assertEqual(loaded["schema_version"], 1)
        self.assertEqual(loaded["project_dir"], "")

    def test_save_and_load_project_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "custom-project"
            project.mkdir()
            path = root / "install.json"

            save_install_config(project, path, backup_existing=False)
            loaded = load_install_config(path)

        self.assertEqual(loaded["project_dir"], str(project.resolve()))

    def test_save_backs_up_existing_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "install.json"
            path.write_text(
                json.dumps({"schema_version": 1, "project_dir": "/old"}),
                encoding="utf-8",
            )
            project = root / "new-project"
            project.mkdir()

            save_install_config(project, path)
            backup = path.with_suffix(".json.bak")

            self.assertTrue(backup.exists())
            prior = json.loads(backup.read_text(encoding="utf-8"))
            self.assertEqual(prior["project_dir"], "/old")


if __name__ == "__main__":
    unittest.main()
