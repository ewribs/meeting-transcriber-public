from pathlib import Path

from config import ARCHIVE_DIR
from meeting_selector import (
    load_meeting_index,
)


def restore_resumed_session(
    resumed_session: dict,
) -> tuple[list[Path], list[dict]]:
    meeting_dirs = [
        ARCHIVE_DIR / meeting_run
        for meeting_run in resumed_session.get(
            "meeting_runs",
            [],
        )
    ]

    resumed_runs = set(
        resumed_session.get(
            "meeting_runs",
            [],
        )
    )

    selected = []

    for meeting in load_meeting_index():
        meeting_run = meeting.get(
            "meeting_run"
        )

        if meeting_run not in resumed_runs:
            continue

        participants = meeting.get(
            "participants",
            [],
        )

        participant_count = len(
            participants
        )

        if participant_count == 1:
            relevance_weight = 3
        elif participant_count <= 3:
            relevance_weight = 2
        else:
            relevance_weight = 1

        selected.append(
            {
                "meeting_dir": Path(
                    meeting["location"]
                ),
                "meeting_run": meeting_run,
                "display_title": meeting.get(
                    "display_title",
                    meeting_run,
                ),
                "participants": participants,
                "participant_count": (
                    participant_count
                ),
                "relevance_weight": (
                    relevance_weight
                ),
            }
        )

    return (
        meeting_dirs,
        selected,
    )
