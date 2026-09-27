import io
import sys
import types
import unittest

from pathlib import Path
from unittest.mock import patch

import transcribe_bridge


class TranscribeBridgeTests(
    unittest.TestCase
):
    def setUp(self):
        self.events = []

        self.emit_patcher = patch(
            "transcribe_bridge.emit_event",
            side_effect=self._capture_event,
        )
        self.emit_patcher.start()

    def tearDown(self):
        self.emit_patcher.stop()

    def _capture_event(
        self,
        event_type,
        **kwargs,
    ):
        self.events.append(
            {
                "type": event_type,
                **kwargs,
            }
        )

    def test_transcribe_without_auto_publish(
        self,
    ):
        fake_transcribe = types.ModuleType(
            "transcribe"
        )

        def fake_transcribe_meeting(
            source_path,
            progress_callback=None,
        ):
            if progress_callback:
                progress_callback(
                    "Working...",
                    50,
                )
            return Path(
                "/tmp/run-a"
            )

        fake_transcribe.transcribe_meeting = (
            fake_transcribe_meeting
        )

        with patch.dict(
            sys.modules,
            {
                "transcribe":
                    fake_transcribe,
            },
        ):
            result = (
                transcribe_bridge
                .transcribe_recording(
                    Path("/tmp/a.m4a"),
                    auto_publish=False,
                )
            )

        self.assertEqual(
            result["status"],
            "Ready to Publish",
        )

        self.assertEqual(
            self.events[-1]["type"],
            "completed",
        )
        self.assertEqual(
            self.events[-1]["status"],
            "Ready to Publish",
        )

    def test_transcribe_auto_publish_reuses_publish_workflow(
        self,
    ):
        fake_transcribe = types.ModuleType(
            "transcribe"
        )
        fake_publish = types.ModuleType(
            "publish_workflow"
        )

        fake_transcribe.transcribe_meeting = (
            lambda source_path,
            progress_callback=None:
                Path("/tmp/run-a")
        )

        def fake_publish_and_archive(
            run_dir,
            progress_callback=None,
        ):
            if progress_callback:
                progress_callback(
                    "Publishing...",
                    60,
                )

            return {
                "archived_path":
                    Path("/archive/run-a")
            }

        fake_publish.publish_and_archive_meeting = (
            fake_publish_and_archive
        )

        with patch.dict(
            sys.modules,
            {
                "transcribe":
                    fake_transcribe,
                "publish_workflow":
                    fake_publish,
            },
        ):
            result = (
                transcribe_bridge
                .transcribe_recording(
                    Path("/tmp/a.m4a"),
                    auto_publish=True,
                )
            )

        self.assertEqual(
            result["status"],
            "Published",
        )
        self.assertEqual(
            self.events[-1]["type"],
            "completed",
        )
        self.assertEqual(
            self.events[-1]["status"],
            "Published",
        )

    def test_publish_failure_preserves_run(
        self,
    ):
        fake_publish = types.ModuleType(
            "publish_workflow"
        )

        def fake_publish_and_archive(
            run_dir,
            progress_callback=None,
        ):
            raise RuntimeError(
                "archive offline"
            )

        fake_publish.publish_and_archive_meeting = (
            fake_publish_and_archive
        )

        with patch.dict(
            sys.modules,
            {
                "publish_workflow":
                    fake_publish,
            },
        ):
            result = (
                transcribe_bridge
                .publish_existing_run(
                    Path("/tmp/run-a")
                )
            )

        self.assertEqual(
            result["status"],
            "Publish Failed",
        )
        self.assertEqual(
            result["run_dir"],
            Path("/tmp/run-a"),
        )
        self.assertEqual(
            self.events[-1]["type"],
            "publish_failed",
        )


if __name__ == "__main__":
    unittest.main()
