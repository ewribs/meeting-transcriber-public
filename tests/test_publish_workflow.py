from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import publish_workflow


class PublishWorkflowTests(unittest.TestCase):
    def test_missing_run_is_rejected(self):
        with TemporaryDirectory() as tmp:
            archive_dir = Path(tmp) / "archive"
            archive_dir.mkdir()

            with patch.object(
                publish_workflow,
                "ARCHIVE_DIR",
                archive_dir,
            ):
                with self.assertRaises(FileNotFoundError):
                    publish_workflow.publish_and_archive_meeting(
                        Path(tmp) / "missing"
                    )

    def test_unavailable_archive_is_rejected(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            archive_dir = Path(tmp) / "missing_archive"

            with patch.object(
                publish_workflow,
                "ARCHIVE_DIR",
                archive_dir,
            ):
                with self.assertRaises(RuntimeError):
                    publish_workflow.publish_and_archive_meeting(
                        run_dir
                    )

    def test_existing_archive_is_delegated_to_resumable_publisher(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "2026-09-14_0800_Test"
            run_dir.mkdir()
            archive_dir = root / "archive"
            archive_dir.mkdir()
            archived_path = archive_dir / run_dir.name
            archived_path.mkdir()

            with patch.object(
                publish_workflow,
                "ARCHIVE_DIR",
                archive_dir,
            ), patch.object(
                publish_workflow,
                "publish_meeting",
                return_value=archived_path,
            ) as publisher, patch.object(
                publish_workflow,
                "cleanup_old_m4as",
                return_value={"deleted": 0},
            ), patch.object(
                publish_workflow,
                "cleanup_archived_m4as",
                return_value={"deleted": 0},
            ):
                result = publish_workflow.publish_and_archive_meeting(
                    run_dir
                )

            publisher.assert_called_once_with(run_dir)
            self.assertEqual(
                result["archived_path"],
                archived_path,
            )

    def test_publish_applies_retention_and_reports_progress(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "2026-09-14_0800_Test"
            run_dir.mkdir()
            archive_dir = root / "archive"
            archive_dir.mkdir()
            archived_path = archive_dir / run_dir.name
            progress = []

            with patch.object(
                publish_workflow,
                "ARCHIVE_DIR",
                archive_dir,
            ), patch.object(
                publish_workflow,
                "M4A_RETENTION_DAYS",
                30,
            ), patch.object(
                publish_workflow,
                "ARCHIVED_M4A_RETENTION_DAYS",
                365,
            ), patch.object(
                publish_workflow,
                "publish_meeting",
                return_value=archived_path,
            ) as publisher, patch.object(
                publish_workflow,
                "cleanup_old_m4as",
                return_value={"deleted": 1},
            ) as local_cleanup, patch.object(
                publish_workflow,
                "cleanup_archived_m4as",
                return_value={"deleted": 2},
            ) as archive_cleanup:
                result = publish_workflow.publish_and_archive_meeting(
                    run_dir,
                    progress_callback=(
                        lambda message, percent: progress.append(
                            (message, percent)
                        )
                    ),
                )

            publisher.assert_called_once_with(run_dir)
            local_cleanup.assert_called_once_with(
                days=30,
                delete=True,
            )
            archive_cleanup.assert_called_once_with(
                days=365,
                delete=True,
            )
            self.assertEqual(
                result["archived_path"],
                archived_path,
            )
            self.assertEqual(progress[-1][1], 100)

    def test_forever_archive_retention_skips_archive_cleanup(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "2026-09-14_0800_Test"
            run_dir.mkdir()
            archive_dir = root / "archive"
            archive_dir.mkdir()
            archived_path = archive_dir / run_dir.name

            with patch.object(
                publish_workflow,
                "ARCHIVE_DIR",
                archive_dir,
            ), patch.object(
                publish_workflow,
                "ARCHIVED_M4A_RETENTION_DAYS",
                0,
            ), patch.object(
                publish_workflow,
                "publish_meeting",
                return_value=archived_path,
            ), patch.object(
                publish_workflow,
                "cleanup_old_m4as",
                return_value={"deleted": 0},
            ), patch.object(
                publish_workflow,
                "cleanup_archived_m4as",
            ) as archive_cleanup:
                result = publish_workflow.publish_and_archive_meeting(
                    run_dir
                )

            archive_cleanup.assert_not_called()
            self.assertTrue(
                result["archived_retention"]["forever"]
            )


if __name__ == "__main__":
    unittest.main()
