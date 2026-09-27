from bulk_publisher import publish_all_meetings
from config import (
    ARCHIVED_M4A_RETENTION_DAYS,
    M4A_RETENTION_DAYS,
    OUTPUT_DIR,
)

from cleanup_archived_m4as import (
    cleanup_archived_m4as,
)
from cleanup_old_m4as import (
    cleanup_old_m4as,
)


def main():
    publish_all_meetings(
        OUTPUT_DIR,
    )

    print()
    print(
        f"Applying {M4A_RETENTION_DAYS}-day "
        "local M4A retention..."
    )

    result = cleanup_old_m4as(
        days=M4A_RETENTION_DAYS,
        delete=True,
    )

    print(
        f"Old local M4As removed: "
        f"{result['deleted']}"
    )

    if result["deleted_bytes"]:
        print(
            f"Local space reclaimed: "
            f"{result['deleted_bytes'] / 1024 / 1024:.1f} MB"
        )

    if result["skipped"]:
        print(
            f"Old local M4As skipped: "
            f"{len(result['skipped'])}"
        )

        for m4a, reason in result[
            "skipped"
        ]:
            print(
                f"  - {m4a.name}: "
                f"{reason}"
            )

    print()

    if ARCHIVED_M4A_RETENTION_DAYS == 0:
        print(
            "Archived M4A retention: Forever"
        )
        return

    print(
        f"Applying {ARCHIVED_M4A_RETENTION_DAYS}-day "
        "archived M4A retention..."
    )

    archived_result = cleanup_archived_m4as(
        days=ARCHIVED_M4A_RETENTION_DAYS,
        delete=True,
    )

    print(
        f"Old archived M4As removed: "
        f"{archived_result['deleted']}"
    )

    if archived_result["deleted_bytes"]:
        print(
            f"Archive space reclaimed: "
            f"{archived_result['deleted_bytes'] / 1024 / 1024:.1f} MB"
        )

    if archived_result["skipped"]:
        print(
            f"Old archived M4As skipped: "
            f"{len(archived_result['skipped'])}"
        )


if __name__ == "__main__":
    main()
