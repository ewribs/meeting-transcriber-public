from pathlib import Path
from datetime import datetime, timedelta
import json

from config import ARCHIVE_DIR, OUTPUT_DIR


def _normalize_participants(
    participants,
) -> list[str]:
    names = []

    for participant in participants or []:
        if isinstance(participant, dict):
            name = str(
                participant.get("name", "")
            ).strip()
        else:
            name = str(participant).strip()

        if name:
            names.append(name)

    return names


def _prepare_meeting(
    meeting: dict,
    location: Path,
    publish_status: str,
) -> dict:
    prepared = dict(meeting)
    prepared["location"] = str(location)
    prepared["participants"] = (
        _normalize_participants(
            prepared.get("participants")
        )
    )
    prepared["publish_status"] = (
        publish_status
    )
    prepared["is_published"] = (
        publish_status == "Published"
    )
    return prepared


def _load_published_meetings(
    archive_dir: Path,
) -> list[dict]:
    index_path = (
        archive_dir / "meeting_index.json"
    )

    if not index_path.exists():
        return []

    try:
        payload = json.loads(
            index_path.read_text(
                encoding="utf-8",
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return []

    if not isinstance(payload, list):
        return []

    meetings = []

    for meeting in payload:
        if not isinstance(meeting, dict):
            continue

        if meeting.get("superseded_by"):
            continue

        meeting_run = str(
            meeting.get("meeting_run", "")
        ).strip()

        if not meeting_run:
            continue

        location_text = str(
            meeting.get("location", "")
        ).strip()

        location = (
            Path(location_text)
            if location_text
            else archive_dir / meeting_run
        )

        meetings.append(
            _prepare_meeting(
                meeting,
                location,
                "Published",
            )
        )

    return meetings


def _load_local_unpublished_meetings(
    output_dir: Path,
) -> list[dict]:
    if not output_dir.exists():
        return []

    meetings = []

    for metadata_path in output_dir.glob(
        "*/meeting_metadata.json"
    ):
        run_dir = metadata_path.parent

        # meeting_metadata.json is created before the final memory step.
        # Require meeting_memory.json so partially completed runs do not
        # appear as ready meetings while transcription is still finishing.
        if not (
            run_dir / "meeting_memory.json"
        ).exists():
            continue

        try:
            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8",
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            continue

        if not isinstance(metadata, dict):
            continue

        if metadata.get("superseded_by"):
            continue

        meeting_run = str(
            metadata.get(
                "meeting_run",
                run_dir.name,
            )
        ).strip()

        if not meeting_run:
            continue

        metadata["meeting_run"] = meeting_run

        meetings.append(
            _prepare_meeting(
                metadata,
                run_dir,
                "Unpublished",
            )
        )

    return meetings


def load_meeting_index(
    archive_dir: Path = ARCHIVE_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> list[dict]:
    """
    Return the unified meeting catalog used by the application.

    Published meetings come from the archive index. Completed local
    output runs are also included immediately as Unpublished. When the
    same meeting_run exists in both places, the published/archive copy
    wins so callers see one meeting with a stable identity.
    """
    archive_dir = Path(archive_dir)
    output_dir = Path(output_dir)

    by_run = {}

    for meeting in _load_published_meetings(
        archive_dir
    ):
        meeting_run = meeting.get(
            "meeting_run"
        )
        if meeting_run:
            by_run[meeting_run] = meeting

    for meeting in _load_local_unpublished_meetings(
        output_dir
    ):
        meeting_run = meeting.get(
            "meeting_run"
        )
        if (
            meeting_run
            and meeting_run not in by_run
        ):
            by_run[meeting_run] = meeting

    meetings = list(by_run.values())

    meetings.sort(
        key=lambda item: (
            item.get("meeting_datetime", "")
            or item.get("meeting_run", "")
        ),
        reverse=True,
    )

    return meetings


def select_meetings(
    person: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    topic: str | None = None,
    title: str | None = None,
    archive_dir: Path = ARCHIVE_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> list[dict]:
    meetings = load_meeting_index(
        archive_dir,
        output_dir,
    )

    selected = []

    start = (
        datetime.fromisoformat(start_date)
        if start_date
        else None
    )

    end = (
        datetime.fromisoformat(end_date)
        + timedelta(days=1)
        if end_date
        else None
    )

    for meeting in meetings:
        if meeting.get("superseded_by"):
            continue

        meeting_datetime = meeting.get(
            "meeting_datetime"
        )

        if not meeting_datetime:
            continue

        meeting_dt = datetime.fromisoformat(
            meeting_datetime
        )

        if (
            start
            and meeting_dt < start
        ):
            continue

        if (
            end
            and meeting_dt >= end
        ):
            continue

        if person:
            participants = [
                name.lower()
                for name
                in meeting.get(
                    "participants",
                    [],
                )
            ]

            if (
                person.lower()
                not in participants
            ):
                continue

        if title:
            title_search_text = " ".join(
                [
                    str(
                        meeting.get(
                            "display_title",
                            "",
                        )
                    ),
                    str(
                        meeting.get(
                            "meeting_run",
                            "",
                        )
                    ),
                ]
            ).lower()

            if (
                title.lower()
                not in title_search_text
            ):
                continue

        meeting_dir = Path(
            meeting["location"]
        )

        if topic:
            memory_path = (
                meeting_dir
                / "meeting_memory.json"
            )

            if not memory_path.exists():
                continue

            memory = json.loads(
                memory_path.read_text(
                    encoding="utf-8",
                )
            )

            topic_text = " ".join(
                (
                    f"{item.get('topic_key', '')} "
                    f"{item.get('topic', '')} "
                    f"{item.get('summary', '')}"
                )
                for item
                in memory.get(
                    "topics",
                    [],
                )
                if isinstance(
                    item,
                    dict,
                )
            ).lower()

            if (
                topic.lower()
                not in topic_text
            ):
                continue

        participants = meeting.get(
            "participants",
            [],
        )

        selected.append(
            (
                meeting_dt,
                {
                    "meeting_dir": meeting_dir,
                    "meeting_run": meeting.get(
                        "meeting_run",
                        meeting_dir.name,
                    ),
                    "display_title": meeting.get(
                        "display_title",
                        meeting_dir.name,
                    ),
                    "participants": participants,
                    "participant_count": len(
                        participants
                    ),
                    "publish_status": meeting.get(
                        "publish_status",
                        "Published",
                    ),
                    "is_published": bool(
                        meeting.get(
                            "is_published",
                            True,
                        )
                    ),
                    "relevance_weight": (
                        3
                        if len(participants) == 1
                        else 2
                        if len(participants) <= 3
                        else 1
                    ),
                },
            )
        )

    selected.sort(
        key=lambda item: item[0]
    )

    return [
        meeting
        for _, meeting
        in selected
    ]
