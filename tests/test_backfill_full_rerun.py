import json
import tempfile
import unittest
from pathlib import Path

from tools.backfill import backfill_full_rerun as bf


def make_run(root, name, memory=True):
    run = Path(root) / name
    run.mkdir()
    (run / "meeting_transcript.md").write_text("raw", encoding="utf-8")
    (run / "meeting_transcript_cleaned.md").write_text("cleaned", encoding="utf-8")
    (run / "meeting_summary.md").write_text("old summary", encoding="utf-8")
    if memory:
        (run / "meeting_memory.json").write_text('{"old": true}', encoding="utf-8")
    return run


def ok_summary(run_dir, cleaned):
    return "new summary"


def ok_complete(run_dir, summary, cleaned, transcript_html):
    (run_dir / "meeting_summary.md").write_text(summary, encoding="utf-8")
    (run_dir / "meeting_memory.json").write_text('{"new": true}', encoding="utf-8")


def html(run_dir):
    return "<p>x</p>"


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.backups = self.root / "backups"
        self.backups.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, **kw):
        kw.setdefault("summary_fn", ok_summary)
        kw.setdefault("complete_fn", ok_complete)
        return bf.run(self.output, self.backups, html_fn=html, **kw)

    def test_dry_run_changes_nothing(self):
        run = make_run(self.output, "2026-01-01_0900_A")
        self.go(apply_changes=False)
        self.assertEqual((run / "meeting_summary.md").read_text(), "old summary")
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_apply_rebuilds_and_backs_up(self):
        run = make_run(self.output, "2026-01-01_0900_A")
        self.assertEqual(self.go(apply_changes=True), 0)
        self.assertEqual((run / "meeting_summary.md").read_text(), "new summary")
        backup = next(p for p in self.backups.iterdir() if p.is_dir())
        self.assertEqual((backup / run.name / "meeting_summary.md").read_text(), "old summary")
        self.assertEqual((run / "meeting_transcript_cleaned.md").read_text(), "cleaned")
        self.assertEqual((run / "meeting_transcript.md").read_text(), "raw")

    def test_failure_restores_originals_and_continues(self):
        bad = make_run(self.output, "2026-01-01_0900_A")
        good = make_run(self.output, "2026-01-02_0900_B")

        def complete(run_dir, summary, cleaned, transcript_html):
            if run_dir.name.endswith("_A"):
                (run_dir / "meeting_summary.md").write_text("half written", encoding="utf-8")
                raise RuntimeError("model crashed")
            ok_complete(run_dir, summary, cleaned, transcript_html)

        self.assertEqual(self.go(apply_changes=True, complete_fn=complete), 1)
        self.assertEqual((bad / "meeting_summary.md").read_text(), "old summary")
        self.assertEqual((good / "meeting_summary.md").read_text(), "new summary")

    def test_progress_is_saved_and_finished_meetings_are_skipped(self):
        make_run(self.output, "2026-01-01_0900_A")
        self.go(apply_changes=True)
        calls = []

        def summary(run_dir, cleaned):
            calls.append(run_dir.name)
            return "again"

        self.go(apply_changes=True, summary_fn=summary)
        self.assertEqual(calls, [])
        self.go(apply_changes=True, summary_fn=summary, redo=True)
        self.assertEqual(calls, ["2026-01-01_0900_A"])

    def test_filters(self):
        make_run(self.output, "2026-01-01_0900_A")
        make_run(self.output, "2026-01-02_0900_B", memory=False)
        make_run(self.output, "2026-01-03_0900_C")
        (self.output / "not_a_meeting").mkdir()
        names = lambda **kw: [p.name for p in bf.find_runs(self.output, **kw)]
        self.assertEqual(len(names()), 3)
        self.assertEqual(names(only=("_B",)), ["2026-01-02_0900_B"])
        self.assertEqual(names(newest=1), ["2026-01-03_0900_C"])
        self.assertEqual(names(limit=1), ["2026-01-01_0900_A"])
        self.assertEqual(names(missing_memory_only=True), ["2026-01-02_0900_B"])

    def test_exports_folder_is_backed_up_and_restored(self):
        run = make_run(self.output, "2026-01-01_0900_A")
        (run / "exports").mkdir()
        (run / "exports" / "OneNote_x.html").write_text("old export", encoding="utf-8")

        def complete(run_dir, summary, cleaned, transcript_html):
            (run_dir / "exports" / "OneNote_x.html").write_text("new export", encoding="utf-8")
            raise RuntimeError("late failure")

        self.go(apply_changes=True, complete_fn=complete)
        self.assertEqual((run / "exports" / "OneNote_x.html").read_text(), "old export")

    def test_interrupt_restores_the_meeting_and_stops(self):
        run = make_run(self.output, "2026-01-01_0900_A")

        def complete(run_dir, summary, cleaned, transcript_html):
            (run_dir / "meeting_summary.md").write_text("half written", encoding="utf-8")
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.go(apply_changes=True, complete_fn=complete)
        self.assertEqual((run / "meeting_summary.md").read_text(), "old summary")
        self.assertEqual(bf.load_state(self.backups / "backfill_state.json"), {})


if __name__ == "__main__":
    unittest.main()
