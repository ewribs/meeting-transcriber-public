import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline
import recover
from metadata import create_meeting_metadata, update_meeting_participants


class ArtifactLifecycleTests(unittest.TestCase):
    def test_metadata_precedes_structured_consumers_and_is_refreshed_last(self):
        events = []
        run_dir = Path("output/test-run")
        source_path = Path("meetings/test.m4a")

        def record(name, value):
            def side_effect(*args, **kwargs):
                events.append(name)
                return value

            return side_effect

        participants = [{"name": "Alex"}]
        with patch(
            "pipeline.create_meeting_metadata",
            side_effect=record("metadata", run_dir / "meeting_metadata.json"),
        ) as create_metadata, patch(
            "pipeline.run_participant_extraction",
            side_effect=record("participants", participants),
        ), patch(
            "pipeline.update_meeting_participants",
            side_effect=record("participant_metadata", run_dir / "meeting_metadata.json"),
        ), patch(
            "pipeline.run_meeting_memory",
            side_effect=record("memory", run_dir / "meeting_memory.json"),
        ), patch(
            "pipeline.apply_structured_summary_composition",
            side_effect=record("composition", ("composed", "<p>composed</p>")),
        ), patch(
            "pipeline.write_html_outputs",
            side_effect=record(
                "html",
                (
                    run_dir / "meeting_transcript.html",
                    run_dir / "meeting_summary.html",
                ),
            ),
        ), patch(
            "pipeline.export_onenote_summary",
            side_effect=record("onenote", run_dir / "exports" / "OneNote.html"),
        ):
            result = pipeline.complete_post_summary_artifacts(
                run_dir=run_dir,
                meeting_summary="draft",
                cleaned_transcript="cleaned",
                transcript_html="<p>transcript</p>",
                source_path=source_path,
            )

        self.assertEqual(
            events,
            [
                "metadata",
                "participants",
                "participant_metadata",
                "memory",
                "composition",
                "html",
                "onenote",
                "metadata",
            ],
        )
        self.assertEqual(result["meeting_summary"], "composed")
        self.assertEqual(create_metadata.call_count, 2)
        for call in create_metadata.call_args_list:
            self.assertEqual(call.kwargs["source_path"], source_path)

    def test_metadata_refresh_preserves_participants_and_creation_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "2026-09-26_1527_TEST9"
            run_dir.mkdir()
            (run_dir / "meeting_summary.md").write_text(
                "summary",
                encoding="utf-8",
            )

            metadata_path = create_meeting_metadata(run_dir)
            first = json.loads(metadata_path.read_text(encoding="utf-8"))
            participants = [{"name": "Alex"}]
            update_meeting_participants(run_dir, participants)

            export_dir = run_dir / "exports"
            export_dir.mkdir()
            (export_dir / f"OneNote_{run_dir.name}.html").write_text(
                "export",
                encoding="utf-8",
            )
            create_meeting_metadata(run_dir)
            refreshed = json.loads(metadata_path.read_text(encoding="utf-8"))

            self.assertEqual(refreshed["participants"], participants)
            self.assertEqual(refreshed["created_utc"], first["created_utc"])
            self.assertTrue(refreshed["artifacts"]["onenote_export"])

    def test_resume_uses_existing_transcript_and_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "meeting_transcript.md").write_text(
                "raw transcript",
                encoding="utf-8",
            )
            (run_dir / "meeting_transcript_cleaned.md").write_text(
                "cleaned transcript",
                encoding="utf-8",
            )
            (run_dir / "meeting_summary.md").write_text(
                "existing summary",
                encoding="utf-8",
            )

            expected = {"memory_path": run_dir / "meeting_memory.json"}
            with patch(
                "recover.complete_post_summary_artifacts",
                return_value=expected,
            ) as complete:
                result = recover.resume_from_existing_summary(run_dir)

            self.assertEqual(result, expected)
            self.assertEqual(
                complete.call_args.kwargs["meeting_summary"],
                "existing summary",
            )
            self.assertEqual(
                complete.call_args.kwargs["cleaned_transcript"],
                "cleaned transcript",
            )
            self.assertIn(
                "raw transcript",
                complete.call_args.kwargs["transcript_html"],
            )


if __name__ == "__main__":
    unittest.main()
