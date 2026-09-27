from pathlib import Path
import json


def build_meeting_index(
    archive_dir: Path,
) -> Path:
    """
    Build a searchable index of completed meetings.
    """

    meetings = []

    for metadata_path in archive_dir.glob(
        "*/meeting_metadata.json"
    ):
        metadata = json.loads(
            metadata_path.read_text(
                encoding="utf-8",
            )
        )
       
        if metadata.get("superseded_by"):
            continue
 
        metadata["location"] = str(
            metadata_path.parent
        )

        participant_names = []

        for participant in (
            metadata.get("participants")
            or []
        ):
            if not isinstance(
                participant,
                dict,
            ):
                continue

            name = str(
                participant.get(
                    "name",
                    "",
                )
            ).strip()

            if name:
                participant_names.append(
                    name
                )

        metadata["participants"] = (
            participant_names
        )

        meetings.append(metadata)

        meetings.sort(
            key=lambda x: (
                x.get(
                    "meeting_datetime",
                    "",
                )
                or x.get(
                    "meeting_run",
                    "",
                )
            ),
            reverse=True,
        )

    index_path = (
        archive_dir / "meeting_index.json"
    )

    index_path.write_text(
        json.dumps(
            meetings,
            indent=2,
        ),
        encoding="utf-8",
    )

    return index_path
