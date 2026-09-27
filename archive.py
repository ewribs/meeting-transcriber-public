from pathlib import Path
import shutil

from config import ARCHIVE_DIR, MEETINGS_DIR


def find_source_m4a(
    run_dir: Path,
) -> Path:
    """
    Locate the original M4A whose stem matches the run folder suffix.
    """
    matches = [
        path
        for path in MEETINGS_DIR.glob("*.m4a")
        if run_dir.name.endswith(
            "_" + path.stem
        )
    ]

    if not matches:
        raise FileNotFoundError(
            "Original M4A not found for "
            f"{run_dir.name}"
        )

    if len(matches) > 1:
        raise RuntimeError(
            "Multiple original M4As match "
            f"{run_dir.name}: "
            + ", ".join(
                item.name
                for item in matches
            )
        )

    return matches[0]


def archived_source_path(
    archive_dir: Path,
    source_m4a: Path,
) -> Path:
    return (
        archive_dir
        / "source"
        / source_m4a.name
    )


def archive_source_m4a(
    source_m4a: Path,
    archive_dir: Path,
) -> Path:
    source_dir = archive_dir / "source"
    source_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = archived_source_path(
        archive_dir,
        source_m4a,
    )

    shutil.copy2(
        source_m4a,
        destination,
    )

    if (
        not destination.exists()
        or destination.stat().st_size
        != source_m4a.stat().st_size
    ):
        raise RuntimeError(
            "Archived M4A verification failed: "
            f"{destination}"
        )

    return destination


def archived_source_is_verified(
    source_m4a: Path,
    archive_dir: Path,
) -> bool:
    destination = archived_source_path(
        archive_dir,
        source_m4a,
    )

    return (
        destination.exists()
        and destination.is_file()
        and destination.stat().st_size
        == source_m4a.stat().st_size
    )


def archive_only(
    run_dir: Path,
    source_m4a: Path | None = None,
) -> Path:
    """
    Copy a meeting folder and its original M4A into the archive.

    If source_m4a is omitted, it is resolved from MEETINGS_DIR.
    The destination is removed if source-audio archival fails so a
    partially published meeting is not left behind.
    """
    destination = (
        ARCHIVE_DIR / run_dir.name
    )

    if destination.exists():
        raise FileExistsError(
            f"Archive already exists: {destination}"
        )

    source_m4a = (
        source_m4a
        or find_source_m4a(run_dir)
    )

    shutil.copytree(
        run_dir,
        destination,
    )

    try:
        archive_source_m4a(
            source_m4a,
            destination,
        )
    except Exception:
        shutil.rmtree(
            destination,
            ignore_errors=True,
        )
        raise

    return destination


def archive_meeting(
    run_dir: Path,
) -> Path:
    """
    Backward-compatible wrapper around archive_only().
    """
    return archive_only(run_dir)
