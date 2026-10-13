from datetime import datetime, timedelta
from pathlib import Path

from meeting_selector import select_meetings
from query.resume import restore_resumed_session


def select_session_meetings(
    selection_criteria: dict,
) -> list[dict]:
    history_days = selection_criteria.get(
        "history_days"
    )

    start_date = selection_criteria.get(
        "start_date"
    )

    if history_days:
        start_date = (
            datetime.now().date()
            - timedelta(
                days=int(history_days) - 1
            )
        ).isoformat()

    return select_meetings(
        person=selection_criteria.get(
            "person"
        ),
        start_date=start_date,
        end_date=selection_criteria.get(
            "end_date"
        ),
        topic=selection_criteria.get(
            "topic"
        ),
        title=selection_criteria.get(
            "title"
        ),
    )


def build_resumed_session_context(
    resumed_session: dict,
    refresh: bool = False,
) -> dict:
    (
        resumed_meeting_dirs,
        selected,
    ) = restore_resumed_session(
        resumed_session
    )

    meeting_dirs = list(
        resumed_meeting_dirs
    )

    selection_criteria = (
        resumed_session.get(
            "selection_criteria"
        )
    )

    refresh_summary = {
        "added": 0,
        "removed": 0,
        "unchanged": len(selected),
    }

    if refresh:
        if not selection_criteria:
            raise ValueError(
                "This session has no saved "
                "selection criteria to refresh."
            )

        refreshed = select_session_meetings(
            selection_criteria
        )

        previous_runs = {
            meeting["meeting_run"]
            for meeting in selected
        }

        refreshed_runs = {
            meeting["meeting_run"]
            for meeting in refreshed
        }

        refresh_summary = {
            "added": len(
                refreshed_runs
                - previous_runs
            ),
            "removed": len(
                previous_runs
                - refreshed_runs
            ),
            "unchanged": len(
                previous_runs
                & refreshed_runs
            ),
        }

        selected = refreshed

        meeting_dirs = [
            meeting["meeting_dir"]
            for meeting in refreshed
        ]

    return {
        "meeting_dirs": meeting_dirs,
        "selected": selected,
        "selection_criteria": (
            selection_criteria
        ),
        "refresh_summary": refresh_summary,
    }
