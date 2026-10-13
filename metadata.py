from datetime import datetime, timezone
from pathlib import Path
import json
import re

from config import (
    APP_NAME,
    APP_VERSION,
)


def get_meeting_datetime(
    run_dir: Path,
) -> str | None:
    try:
        date_part, time_part, _ = (
            run_dir.name.split("_", 2)
        )

        meeting_dt = datetime.strptime(
            f"{date_part}_{time_part}",
            "%Y-%m-%d_%H%M",
        )

        return meeting_dt.isoformat()

    except ValueError:
        return None


def get_display_title(
    run_dir: Path,
) -> str:
    try:
        _, _, title = run_dir.name.split("_", 2)

        # Remove trailing MMDDYY from recording name.
        title = re.sub(
            r"\d{6}$",
            "",
            title,
        )

        title = title.replace("_", " ")

        # Split CamelCase.
        title = re.sub(
            r"(?<=[a-z])(?=[A-Z])",
            " ",
            title,
        )

        # Preserve acronyms while separating following words.
        title = re.sub(
            r"(?<=[A-Z])(?=[A-Z][a-z])",
            " ",
            title,
        )

        # Make 1v1 readable.
        title = re.sub(
            r"(?<=[A-Za-z])(?=1v1)",
            " ",
            title,
        )

        return title.strip()

    except ValueError:
        return run_dir.name




def _load_processing_runtime(run_dir: Path) -> dict:
    path = run_dir / "processing_runtime.json"
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}

def create_meeting_metadata(
    run_dir: Path,
    source_path: Path | None = None,
) -> Path:
    """
    Create or update meeting_metadata.json.
    """

    metadata_path = (
        run_dir / "meeting_metadata.json"
    )

    existing_metadata = {}

    if metadata_path.exists():
        existing_metadata = json.loads(
            metadata_path.read_text(
                encoding="utf-8"
            )
        )

    processing = _load_processing_runtime(run_dir)

    metadata = {
        "application": APP_NAME,
        "application_version": APP_VERSION,
        "meeting_run": run_dir.name,
        "meeting_datetime": get_meeting_datetime(
            run_dir
        ),
        "display_title": get_display_title(
            run_dir
        ),
        "superseded_by": existing_metadata.get(
            "superseded_by"
        ),
        "participants": existing_metadata.get(
            "participants",
            [],
        ),
        "created_utc": (
            existing_metadata.get("created_utc")
            or datetime.now(timezone.utc).isoformat()
        ),
        "source_path": (
            str(Path(source_path).expanduser().resolve())
            if source_path is not None
            else existing_metadata.get("source_path")
        ),
        "processing": (
            processing
            or existing_metadata.get("processing")
            or {}
        ),

        "artifacts": {
            "transcript": (
                run_dir / "meeting_transcript.md"
            ).exists(),

            "cleaned_transcript": (
                run_dir / "meeting_transcript_cleaned.md"
            ).exists(),

            "summary": (
                run_dir / "meeting_summary.md"
            ).exists(),

            "onenote_export": (
                run_dir / "exports"
                / f"OneNote_{run_dir.name}.html"
            ).exists(),
        },
    }

    metadata_path.write_text(
        json.dumps(
            metadata,
            indent=2,
        ),
        encoding="utf-8",
    )

    return metadata_path


def update_meeting_participants(
    run_dir: Path,
    participants: list[dict],
) -> Path:
    """
    Update only the participants field in
    meeting_metadata.json.

    All other metadata fields are preserved.
    """

    metadata_path = (
        run_dir / "meeting_metadata.json"
    )

    if not metadata_path.exists():
        raise FileNotFoundError(
            f"Meeting metadata not found: "
            f"{metadata_path}"
        )

    metadata = json.loads(
        metadata_path.read_text(
            encoding="utf-8",
        )
    )

    metadata["participants"] = participants

    metadata_path.write_text(
        json.dumps(
            metadata,
            indent=2,
        ),
        encoding="utf-8",
    )

    return metadata_path
