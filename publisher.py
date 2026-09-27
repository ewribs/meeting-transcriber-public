from pathlib import Path

from archive import (
    archive_only,
    archive_source_m4a,
    archived_source_is_verified,
    find_source_m4a,
)
from config import ARCHIVE_DIR
from dashboard_generator import build_meeting_dashboard
from indexer import build_meeting_index
from onenote import copy_onenote_export
from audio_cleanup import remove_wavs


REQUIRED_PUBLISH_ARTIFACTS = (
    "meeting_summary.md",
    "meeting_transcript_cleaned.md",
    "meeting_metadata.json",
    "meeting_memory.json",
)


def _verify_resumable_archive(
    run_dir: Path,
    archived_path: Path,
    source_m4a: Path,
) -> None:
    """
    Confirm an existing archive is the completed first stage of this
    exact local run, so publishing can safely resume after a later
    publish step failed.

    We intentionally do not overwrite or delete an existing archive
    when verification fails.
    """
    if not archived_path.is_dir():
        raise FileExistsError(
            f"Archive path exists but is not a directory: {archived_path}"
        )

    missing = []
    mismatched = []

    for filename in REQUIRED_PUBLISH_ARTIFACTS:
        local_file = run_dir / filename
        archived_file = archived_path / filename

        if not local_file.exists():
            missing.append(f"local:{filename}")
            continue

        if not archived_file.exists():
            missing.append(f"archive:{filename}")
            continue

        if local_file.stat().st_size != archived_file.stat().st_size:
            mismatched.append(filename)

    if missing or mismatched:
        details = []

        if missing:
            details.append(
                "missing " + ", ".join(missing)
            )

        if mismatched:
            details.append(
                "size mismatch " + ", ".join(mismatched)
            )

        raise FileExistsError(
            "Archive already exists but cannot be safely resumed: "
            f"{archived_path} ({'; '.join(details)})"
        )

    # The core archive matches this exact local run. If the source M4A
    # was the step that failed, repair only that file and verify it
    # before allowing the remaining publish steps to resume.
    if not archived_source_is_verified(
        source_m4a,
        archived_path,
    ):
        archive_source_m4a(
            source_m4a,
            archived_path,
        )

        if not archived_source_is_verified(
            source_m4a,
            archived_path,
        ):
            raise FileExistsError(
                "Archive source M4A could not be safely repaired: "
                f"{archived_path / 'source' / source_m4a.name}"
            )


def publish_meeting(
    run_dir: Path,
) -> Path:
    """
    Publish a completed meeting into the archive library.

    Steps:
    1. Archive meeting folder
    2. Copy OneNote export to import folder
    3. Rebuild archive index
    4. Rebuild archive dashboard

    Returns:
        Archived meeting path
    """

    source_m4a = find_source_m4a(
        run_dir
    )

    archived_path = (
        ARCHIVE_DIR / run_dir.name
    )

    if archived_path.exists():
        _verify_resumable_archive(
            run_dir,
            archived_path,
            source_m4a,
        )
    else:
        archived_path = archive_only(
            run_dir,
            source_m4a=source_m4a,
        )

    copy_onenote_export(
        run_dir,
    )

    index_path = build_meeting_index(
        ARCHIVE_DIR,
    )

    build_meeting_dashboard(
        index_path,
    )

    remove_wavs(
        archived_path,
    )

    remove_wavs(
        run_dir,
    )

    return archived_path
