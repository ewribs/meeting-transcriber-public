import json
import tempfile
import unittest
from pathlib import Path

from meeting_delete_service import (
    finalize_published_meeting_unpublish,
    finalize_unpublished_meeting_delete,
    remove_meeting_from_saved_sessions,
    resolve_published_meeting_unpublish_plan,
    resolve_unpublished_meeting_delete_plan,
)


def _make_run(tmp_path: Path, run: str, *, source_path: Path | None = None):
    output = tmp_path / "output"
    run_dir = output / run
    run_dir.mkdir(parents=True)
    payload = {
        "meeting_run": run,
        "meeting_datetime": "2026-09-24T12:47:00",
        "display_title": "Disposable Test Meeting",
        "participants": [],
    }
    if source_path is not None:
        payload["source_path"] = str(source_path)
    (run_dir / "meeting_metadata.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    (run_dir / "meeting_memory.json").write_text("{}", encoding="utf-8")
    return output, run_dir


def _write_session(archive: Path, name: str, runs: list[str], *, with_cache=True):
    sessions = archive / "query_sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_name": name,
        "meeting_runs": runs,
        "conversation_history": [{"role": "user", "content": "hello"}],
    }
    if with_cache:
        payload["changes_cache"] = {"meeting_runs": runs[:2]}
    path = sessions / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class MeetingDeleteServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_delete_plan_marks_recordings_folder_source_as_managed(self):
        recordings = self.tmp_path / "recordings"
        recordings.mkdir()
        source = recordings / "custom.m4a"
        source.write_bytes(b"audio")
        run = "2026-09-24_1247_Disposable"
        output, _ = _make_run(self.tmp_path, run, source_path=source)

        plan = resolve_unpublished_meeting_delete_plan(
            run,
            output_dir=output,
            recordings_dir=recordings,
            meetings_dir=self.tmp_path / "meetings",
            archive_dir=self.tmp_path / "archive",
        )

        self.assertTrue(plan["source_found"])
        self.assertEqual(plan["source_path"], str(source.resolve()))
        self.assertTrue(plan["source_is_managed"])

    def test_delete_plan_keeps_external_import_conservative(self):
        recordings = self.tmp_path / "recordings"
        recordings.mkdir()
        external = self.tmp_path / "external" / "imported.m4a"
        external.parent.mkdir()
        external.write_bytes(b"audio")
        run = "2026-09-24_1247_Imported"
        output, _ = _make_run(self.tmp_path, run, source_path=external)

        plan = resolve_unpublished_meeting_delete_plan(
            run,
            output_dir=output,
            recordings_dir=recordings,
            meetings_dir=self.tmp_path / "meetings",
            archive_dir=self.tmp_path / "archive",
        )

        self.assertTrue(plan["source_found"])
        self.assertFalse(plan["source_is_managed"])

    def test_finalize_delete_requires_run_folder_already_moved(self):
        run = "2026-09-24_1247_Disposable"
        output, run_dir = _make_run(self.tmp_path, run)

        with self.assertRaises(RuntimeError):
            finalize_unpublished_meeting_delete(
                run,
                output_dir=output,
                archive_dir=self.tmp_path / "archive",
            )

        run_dir.rename(self.tmp_path / "trashed-run")
        result = finalize_unpublished_meeting_delete(
            run,
            output_dir=output,
            archive_dir=self.tmp_path / "archive",
        )
        self.assertTrue(result["deleted"])

    def test_saved_session_reference_cleanup_preserves_other_state(self):
        archive = self.tmp_path / "archive"
        run = "2026-09-24_1247_DeleteMe"
        keep = "2026-09-23_0900_KeepMe"
        path = _write_session(archive, "Boss", [run, keep])

        result = remove_meeting_from_saved_sessions(run, archive_dir=archive)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(result["updated_session_count"], 1)
        self.assertEqual(payload["meeting_runs"], [keep])
        self.assertTrue(payload["conversation_history"])
        self.assertNotIn("changes_cache", payload)

    def test_unpublish_plan_requires_local_copy_and_reports_session_refs(self):
        run = "2026-09-24_1247_Published"
        archive = self.tmp_path / "archive"
        output = self.tmp_path / "output"
        archive_run = archive / run
        local_run = output / run
        archive_run.mkdir(parents=True)
        local_run.mkdir(parents=True)
        (archive_run / "meeting_metadata.json").write_text(
            json.dumps({"meeting_run": run, "display_title": "Published Test"}),
            encoding="utf-8",
        )
        _write_session(archive, "Published Ref", [run])

        plan = resolve_published_meeting_unpublish_plan(
            run,
            archive_dir=archive,
            output_dir=output,
        )
        self.assertEqual(plan["archive_path"], str(archive_run.resolve()))
        self.assertEqual(plan["local_run_path"], str(local_run.resolve()))
        self.assertEqual(plan["session_reference_count"], 1)

    def test_finalize_unpublish_rebuilds_index_and_prunes_sessions(self):
        run = "2026-09-24_1247_Published"
        keep = "2026-09-23_0900_Keep"
        archive = self.tmp_path / "archive"
        output = self.tmp_path / "output"
        archive.mkdir()
        local_run = output / run
        local_run.mkdir(parents=True)
        _write_session(archive, "Published Ref", [run, keep])

        result = finalize_published_meeting_unpublish(
            run,
            archive_dir=archive,
            output_dir=output,
        )

        session = json.loads(
            (archive / "query_sessions" / "Published Ref.json").read_text(
                encoding="utf-8"
            )
        )
        index = json.loads((archive / "meeting_index.json").read_text(encoding="utf-8"))

        self.assertTrue(result["unpublished"])
        self.assertEqual(result["updated_session_count"], 1)
        self.assertEqual(session["meeting_runs"], [keep])
        self.assertEqual(index, [])

    def test_metadata_persists_source_path(self):
        from metadata import create_meeting_metadata

        run_dir = self.tmp_path / "2026-09-24_1247_SourcePersist"
        run_dir.mkdir()
        source = self.tmp_path / "recordings" / "SourcePersist.m4a"
        source.parent.mkdir()
        source.write_bytes(b"audio")

        metadata_path = create_meeting_metadata(
            run_dir,
            source_path=source,
        )
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["source_path"], str(source.resolve()))

    def test_delete_plan_ignores_display_placeholder_source_path(self):
        run = "2026-09-24_1300_Placeholder"
        output = self.tmp_path / "output"
        run_dir = output / run
        run_dir.mkdir(parents=True)
        (run_dir / "meeting_metadata.json").write_text(
            json.dumps(
                {
                    "meeting_run": run,
                    "display_title": "Placeholder Test",
                    "source_path": "N/A",
                }
            ),
            encoding="utf-8",
        )

        plan = resolve_unpublished_meeting_delete_plan(
            run,
            output_dir=output,
            recordings_dir=self.tmp_path / "recordings",
            meetings_dir=self.tmp_path / "meetings",
            archive_dir=self.tmp_path / "archive",
        )

        self.assertIsNone(plan["source_path"])


if __name__ == "__main__":
    unittest.main()
