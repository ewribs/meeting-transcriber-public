import argparse
from datetime import datetime, timedelta
from pathlib import Path

from cleanup_old_m4as import archive_is_complete
from config import (
    ARCHIVE_DIR,
    ARCHIVED_M4A_RETENTION_DAYS,
)


def cleanup_archived_m4as(
    days: int = ARCHIVED_M4A_RETENTION_DAYS,
    delete: bool = False,
) -> dict:
    if days < 0:
        raise ValueError(
            "Archived M4A retention cannot be negative."
        )

    if not ARCHIVE_DIR.exists():
        raise RuntimeError(
            f"Archive unavailable: {ARCHIVE_DIR}"
        )

    if days == 0:
        return {
            "eligible": [],
            "skipped": [],
            "total_bytes": 0,
            "deleted": 0,
            "deleted_bytes": 0,
            "days": days,
            "forever": True,
        }

    cutoff = (
        datetime.now()
        - timedelta(days=days)
    )

    eligible = []
    skipped = []

    for archive_dir in sorted(
        path
        for path in ARCHIVE_DIR.iterdir()
        if path.is_dir()
    ):
        source_dir = archive_dir / "source"

        if not source_dir.exists():
            continue

        for m4a in sorted(
            source_dir.glob("*.m4a")
        ):
            modified = datetime.fromtimestamp(
                m4a.stat().st_mtime
            )

            if modified > cutoff:
                continue

            complete, missing = (
                archive_is_complete(
                    archive_dir
                )
            )

            if not complete:
                skipped.append(
                    (
                        m4a,
                        "archive missing: "
                        + ", ".join(missing),
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
        for m4a, _ in eligible
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
        "forever": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Remove archived source M4As after the configured "
            "retention period while keeping derived meeting artifacts."
        )
    )

    parser.add_argument(
        "--days",
        type=int,
        default=ARCHIVED_M4A_RETENTION_DAYS,
        help=(
            "Minimum age in days before an archived M4A is "
            "eligible for deletion. Use 0 for Forever."
        ),
    )

    parser.add_argument(
        "--delete",
        action="store_true",
        help=(
            "Actually delete eligible archived M4As. Without this "
            "flag, perform a dry run."
        ),
    )

    args = parser.parse_args()

    result = cleanup_archived_m4as(
        days=args.days,
        delete=args.delete,
    )

    print()
    print("Archived M4A Cleanup")
    print("--------------------")
    print(
        "Mode:",
        "DELETE"
        if args.delete
        else "DRY RUN",
    )
    print(
        "Retention:",
        "Forever"
        if args.days == 0
        else f"{args.days} days",
    )
    print()

    for m4a, archive_dir in result["eligible"]:
        action = (
            "DELETE"
            if args.delete
            else "WOULD DELETE"
        )
        print(f"{action} {m4a}")
        print(f"  Meeting: {archive_dir.name}")
        print()

    for m4a, reason in result["skipped"]:
        print(f"SKIP {m4a}")
        print(f"  Reason: {reason}")
        print()

    print("Summary")
    print("-------")
    print(
        f"Eligible archived M4As: "
        f"{len(result['eligible'])}"
    )
    print(
        f"Deleted archived M4As: "
        f"{result['deleted']}"
    )


if __name__ == "__main__":
    main()
