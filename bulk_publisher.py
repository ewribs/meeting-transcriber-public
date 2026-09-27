from pathlib import Path

from config import ARCHIVE_DIR
from archive import archive_only, find_source_m4a

from indexer import build_meeting_index
from dashboard_generator import build_meeting_dashboard

from onenote import copy_onenote_export

from audio_cleanup import remove_wavs

def find_local_meetings(
    output_dir: Path,
):
    """
    Find completed meeting folders in local output.
    """

    meetings = []

    for item in output_dir.iterdir():
        if (
            item.is_dir()
            and item.name != "html_test"
            and item.name != "Pilot Files"
        ):
            meetings.append(item)

    return sorted(meetings)


def get_archive_status(
    meetings,
):
    """
    Compare local meetings against archive.
    """

    ready = []
    archived = []

    for meeting in meetings:
        archive_path = (
            ARCHIVE_DIR / meeting.name
        )

        if archive_path.exists():
            archived.append(meeting)
        else:
            ready.append(meeting)

    return ready, archived


def publish_all_meetings(
    output_dir: Path,
):
    """
    Publish all missing meetings.

    Copies meetings first, then rebuilds
    archive index and dashboard once.
    """

    meetings = find_local_meetings(
        output_dir,
    )

    ready, archived = get_archive_status(
        meetings,
    )

    print()
    print("Meeting Archive Publisher")
    print("------------------------")
    print()

    print(
        f"Local meetings found: {len(meetings)}"
    )

    print()
    print("Ready to publish:")

    for meeting in ready:
        print(
            f"  ✓ {meeting.name}"
        )

    print()

    print(
        f"Already archived: {len(archived)}"
    )

    if not ready:
        print()
        print("Nothing to publish.")
        return

    print()

    confirmation = input(
        f"Publish {len(ready)} meetings? (y/n): "
    )

    if confirmation.lower() != "y":
        print("Cancelled.")
        return

    print()
    print("Publishing...")

    published = 0

    successfully_published = []

    for meeting in ready:
        try:
            source_m4a = find_source_m4a(
                meeting
            )

            archived_path = archive_only(
                meeting,
                source_m4a=source_m4a,
            )

            copy_onenote_export(
                meeting,
            )

            successfully_published.append(
                (
                    meeting,
                    archived_path,
                )
            )

            remove_wavs(
                archived_path,
            )

            remove_wavs(
                meeting,
            )

            print(
                f"✓ {meeting.name}"
            )

            published += 1

        except Exception as e:
            print(
                f"FAILED {meeting.name}: {e}"
            )

    print()

    print(
        "Refreshing archive index..."
    )

    index_path = build_meeting_index(
        ARCHIVE_DIR,
    )

    print(
        "Refreshing archive dashboard..."
    )

    build_meeting_dashboard(
        index_path,
    )

    print()

    print(
        f"Complete: {published} published"
    )
