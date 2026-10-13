import argparse
from datetime import datetime, timedelta
from pathlib import Path

from archive import archived_source_is_verified
from config import (
    ARCHIVE_DIR,
    M4A_RETENTION_DAYS,
    MEETINGS_DIR,
)

def _looks_like_meeting_archive(name: str) -> bool:
    """Return True for timestamped meeting archive directory names.

    Expected prefix: YYYY-MM-DD_....  This intentionally avoids tying
    retention to a specific calendar year.
    """
    if len(name) < 11:
        return False

    prefix = name[:11]
    return (
        prefix[0:4].isdigit()
        and prefix[4] == "-"
        and prefix[5:7].isdigit()
        and prefix[7] == "-"
        and prefix[8:10].isdigit()
        and prefix[10] == "_"
    )


REQUIRED_ARCHIVE_ARTIFACTS = (
    "meeting_summary.md",
    "meeting_transcript_cleaned.md",
    "meeting_metadata.json",
    "meeting_memory.json",
)


def archive_is_complete(
    archive_dir: Path,
) -> tuple[bool, list[str]]:
    missing = [
        artifact
        for artifact in REQUIRED_ARCHIVE_ARTIFACTS
        if not (
            archive_dir / artifact
        ).exists()
    ]

    return (
        not missing,
        missing,
    )


def cleanup_old_m4as(
    days: int = M4A_RETENTION_DAYS,
    delete: bool = False,
) -> dict:
    if not ARCHIVE_DIR.exists():
        raise RuntimeError(
            f"Archive unavailable: "
            f"{ARCHIVE_DIR}"
        )

    cutoff = (
        datetime.now()
        - timedelta(
            days=days
        )
    )

    archive_dirs = [
        path
        for path in ARCHIVE_DIR.iterdir()
        if (
            path.is_dir()
            and _looks_like_meeting_archive(path.name)
        )
    ]

    eligible = []
    skipped = []

    for m4a in sorted(
        MEETINGS_DIR.glob("*.m4a")
    ):
        modified = datetime.fromtimestamp(
            m4a.stat().st_mtime
        )

        if modified > cutoff:
            continue

        matches = [
            archive_dir
            for archive_dir
            in archive_dirs
            if archive_dir.name.endswith(
                "_" + m4a.stem
            )
        ]

        if len(matches) == 0:
            skipped.append(
                (
                    m4a,
                    "no matching archive",
                )
            )
            continue

        if len(matches) > 1:
            skipped.append(
                (
                    m4a,
                    (
                        "multiple matching archives: "
                        + ", ".join(
                            item.name
                            for item in matches
                        )
                    ),
                )
            )
            continue

        archive_dir = matches[0]

        complete, missing = (
            archive_is_complete(
                archive_dir
            )
        )

        if not complete:
            skipped.append(
                (
                    m4a,
                    (
                        "archive missing: "
                        + ", ".join(missing)
                    ),
                )
            )
            continue

        if not archived_source_is_verified(
            m4a,
            archive_dir,
        ):
            skipped.append(
                (
                    m4a,
                    "archived source M4A missing or size mismatch",
                )
            )
            continue

        eligible.append(
            (
                m4a,
                archive_dir,
            )
        )

    total_bytes = sum(
        m4a.stat().st_size
        for m4a, _
        in eligible
    )

    deleted = 0
    deleted_bytes = 0

    if delete:
        for m4a, _ in eligible:
            size = m4a.stat().st_size

            m4a.unlink()

            deleted += 1
            deleted_bytes += size

    return {
        "eligible": eligible,
        "skipped": skipped,
        "total_bytes": total_bytes,
        "deleted": deleted,
        "deleted_bytes": deleted_bytes,
        "days": days,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Remove old original M4A recordings "
            "after confirming a complete archive."
        )
    )

    parser.add_argument(
        "--days",
        type=int,
        default=M4A_RETENTION_DAYS,
        help=(
            "Minimum age in days before an M4A "
            "is eligible for deletion."
        ),
    )

    parser.add_argument(
        "--delete",
        action="store_true",
        help=(
            "Actually delete eligible M4As. "
            "Without this flag, perform a dry run."
        ),
    )

    args = parser.parse_args()

    result = cleanup_old_m4as(
        days=args.days,
        delete=args.delete,
    )

    eligible = result["eligible"]
    skipped = result["skipped"]
    total_bytes = result[
        "total_bytes"
    ]

    print()
    print("Old M4A Cleanup")
    print("---------------")
    print(
        "Mode:",
        "DELETE"
        if args.delete
        else "DRY RUN",
    )
    print(
        f"Retention: {args.days} days"
    )
    print()

    for m4a, archive_dir in eligible:
        action = (
            "DELETE"
            if args.delete
            else "WOULD DELETE"
        )

        print(
            f"{action} {m4a.name}"
        )
        print(
            f"  Archive: "
            f"{archive_dir.name}"
        )
        print()

    for m4a, reason in skipped:
        print(
            f"SKIP {m4a.name}"
        )
        print(
            f"  Reason: {reason}"
        )
        print()

    print("Summary")
    print("-------")
    print(
        f"Eligible M4As: "
        f"{len(eligible)}"
    )
    print(
        f"Skipped M4As: "
        f"{len(skipped)}"
    )
    print(
        f"Eligible space: "
        f"{total_bytes / 1024 / 1024 / 1024:.2f} GB"
    )

    if not args.delete:
        print()
        print(
            "Dry run only. "
            "Nothing was deleted."
        )


if __name__ == "__main__":
    main()
