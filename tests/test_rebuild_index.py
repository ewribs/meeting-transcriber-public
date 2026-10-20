import tempfile
import unittest
from pathlib import Path

from tools import rebuild_index


class RebuildIndexTests(unittest.TestCase):
    def test_missing_folder_is_reported(self):
        self.assertEqual(rebuild_index.main(["--archive", "/no/such/folder"]), 1)

    def test_folder_without_meetings_is_not_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rebuild_index.main(["--archive", tmp]), 1)
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
