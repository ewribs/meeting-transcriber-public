from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicReleasePermissionTests(unittest.TestCase):
    def make_archive(self, root: Path) -> Path:
        source = root / "source"
        source.mkdir()

        executable = source / "tool.sh"
        executable.write_text("#!/bin/bash\necho ok\n")
        executable.chmod(0o755)

        regular = source / "README.txt"
        regular.write_text("hello\n")
        regular.chmod(0o644)

        archive = root / "test.zip"

        with zipfile.ZipFile(
            archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zf:
            zf.write(executable, arcname="tool.sh")
            zf.write(regular, arcname="README.txt")

        return archive

    def assert_permissions_preserved(self, helper) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self.make_archive(root)
            destination = root / "destination"

            helper(archive, destination)

            executable_mode = (
                destination / "tool.sh"
            ).stat().st_mode & 0o777

            regular_mode = (
                destination / "README.txt"
            ).stat().st_mode & 0o777

            self.assertEqual(executable_mode, 0o755)
            self.assertEqual(regular_mode, 0o644)

    def test_public_release_builder_preserves_permissions(self):
        module = load_module(
            "build_public_release_test",
            "tools/build_public_release.py",
        )
        self.assert_permissions_preserved(
            module.extract_zip_preserving_permissions
        )

    def test_public_sync_preserves_permissions(self):
        module = load_module(
            "sync_public_release_test",
            "tools/sync_public_release.py",
        )
        self.assert_permissions_preserved(
            module.extract_zip_preserving_permissions
        )


if __name__ == "__main__":
    unittest.main()
