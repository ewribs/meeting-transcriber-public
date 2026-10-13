import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "maintenance"))
import check_updates as c


class ParseTests(unittest.TestCase):
    def test_brew_keeps_only_watched(self):
        text = json.dumps({"formulae": [
            {"name": "ffmpeg", "installed_versions": ["7.0"], "current_version": "7.1"},
            {"name": "wget", "installed_versions": ["1"], "current_version": "2"}]})
        self.assertEqual(c.parse_brew_outdated(text), [("ffmpeg", "7.0", "7.1")])
        self.assertEqual(c.parse_brew_outdated(""), [])

    def test_pip_keeps_only_watched(self):
        text = json.dumps([{"name": "mlx-lm", "version": "1", "latest_version": "2"},
                           {"name": "requests", "version": "1", "latest_version": "2"}])
        self.assertEqual(c.parse_pip_outdated(text), [("mlx-lm", "1", "2")])

    def test_local_revision_and_lfs_lookup(self):
        with tempfile.TemporaryDirectory() as t:
            ref = Path(t) / "models--a--b" / "refs" / "main"
            ref.parent.mkdir(parents=True)
            ref.write_text("abc123\n")
            self.assertEqual(c.local_hf_revision("a/b", t), "abc123")
            self.assertIsNone(c.local_hf_revision("x/y", t))
        tree = [{"path": "m.bin", "lfs": {"oid": "deadbeef"}}, {"path": "n.bin"}]
        self.assertEqual(c.find_lfs_sha256(tree, "m.bin"), "deadbeef")
        self.assertIsNone(c.find_lfs_sha256(tree, "n.bin"))


if __name__ == "__main__":
    unittest.main()
