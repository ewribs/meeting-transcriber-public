import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "backfill"))
import sync_rebuilt_to_archive as s


class SyncTests(unittest.TestCase):
    def test_backs_up_and_overwrites_only_listed_files(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            local, arch, bk = t / "l" / "m", t / "a" / "m", t / "b"
            for d in (local, arch, local / "exports", arch / "exports"):
                d.mkdir(parents=True, exist_ok=True)
            (local / "meeting_memory.json").write_text("new")
            (arch / "meeting_memory.json").write_text("old")
            (local / "meeting_summary.md").write_text("same")
            (arch / "meeting_summary.md").write_text("same")
            (local / "exports" / "x.html").write_text("n")
            (local / "audio.m4a").write_text("local audio")
            (arch / "audio.m4a").write_text("archive audio")
            changed = s.sync_meeting(local, arch, bk)
            self.assertEqual(sorted(changed), ["exports/x.html", "meeting_memory.json"])
            self.assertEqual((arch / "meeting_memory.json").read_text(), "new")
            self.assertEqual((bk / "m" / "meeting_memory.json").read_text(), "old")
            self.assertEqual((arch / "audio.m4a").read_text(), "archive audio")


if __name__ == "__main__":
    unittest.main()
