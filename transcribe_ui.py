from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TERMINAL_STATUSES = {
    "Published",
    "Ready to Publish",
    "Failed",
    "Publish Failed",
}


@dataclass(frozen=True)
class QueueActionState:
    remove_selected: bool
    clear_completed: bool
    retry_failed: bool


def queue_action_state(
    entries: list[dict],
    selected_row: int,
    *,
    active: bool,
) -> QueueActionState:
    statuses = {str(entry.get("status", "")) for entry in entries}
    has_selection = 0 <= selected_row < len(entries)
    return QueueActionState(
        remove_selected=has_selection and not active,
        clear_completed=bool(statuses & {"Published", "Ready to Publish"})
        and not active,
        retry_failed=bool(statuses & {"Failed", "Publish Failed"})
        and not active,
    )


def queue_rows(entries: Iterable[dict]) -> list[tuple[str, str | None]]:
    rows: list[tuple[str, str | None]] = []
    for index, entry in enumerate(entries, start=1):
        source_path = Path(entry["source_path"])
        status = str(entry.get("status", ""))
        error = entry.get("error")
        rows.append(
            (
                f"{index}. {source_path.name} — {status}",
                None if not error else str(error),
            )
        )
    return rows


def source_summary(
    source_path: Path | None,
    *,
    output_dir: Path,
    archive_dir: Path,
) -> tuple[str, str]:
    if source_path is None:
        return "", "Current source: None"

    source_path = Path(source_path)
    return (
        str(source_path),
        "Current source: "
        f"{source_path.name}\n\n"
        f"Source: {source_path}\n"
        f"Working folder: {output_dir}\n"
        f"Archive folder: {archive_dir}",
    )


def workflow_idle() -> str:
    return (
        "1. Intake — add one or more M4A recordings\n"
        "2. Transcribe — waiting for queue\n"
        "3. Review — waiting for transcription\n"
        "4. Publish & Archive — waiting for review"
    )


def workflow_queued() -> str:
    return (
        "1. Intake — recordings queued ✓\n"
        "2. Transcribe — ready\n"
        "3. Review — waiting for transcription\n"
        "4. Publish & Archive — waiting for review"
    )


def workflow_running(*, auto_publish: bool) -> str:
    publish_line = (
        "4. Publish & Archive — automatic after each transcription"
        if auto_publish
        else "4. Publish & Archive — completed meetings remain Unpublished"
    )
    return (
        "1. Intake — recordings queued ✓\n"
        "2. Transcribe — queue running…\n"
        "3. Review — generated artifacts checked per meeting\n"
        f"{publish_line}"
    )


def workflow_complete(
    *,
    auto_publish: bool,
    transcription_failures: int,
    publish_failures: int,
) -> str:
    if transcription_failures or publish_failures:
        return (
            "1. Intake — queue complete ✓\n"
            "2. Transcribe — complete with failures ⚠\n"
            "3. Review — successful artifacts retained locally\n"
            "4. Publish & Archive — review remaining Unpublished meetings in Meetings"
        )
    if auto_publish:
        return (
            "1. Intake — queue complete ✓\n"
            "2. Transcribe — complete ✓\n"
            "3. Review — generated artifacts ready ✓\n"
            "4. Publish & Archive — automatic publish complete ✓"
        )
    return (
        "1. Intake — queue complete ✓\n"
        "2. Transcribe — complete ✓\n"
        "3. Review — generated artifacts ready ✓\n"
        "4. Publish & Archive — meeting(s) are Unpublished; manage in Meetings"
    )


def queue_completion_detail(
    *,
    auto_publish: bool,
    successes: int,
    transcription_failures: int,
    published: int,
    publish_failures: int,
) -> str:
    if auto_publish:
        return (
            f"Queue complete: {successes} transcribed, "
            f"{published} published, {transcription_failures} transcription "
            f"failure(s), {publish_failures} publish failure(s)."
        )
    return (
        f"Queue complete: {successes} succeeded, "
        f"{transcription_failures} failed. Successful meetings are Unpublished "
        "and ready in Meetings."
    )


def queue_completion_message(
    *,
    auto_publish: bool,
    total: int,
    successes: int,
    transcription_failures: int,
    published: int,
    publish_failures: int,
) -> str:
    if auto_publish:
        return (
            f"Processed {total} recording(s).\n\n"
            f"Transcribed: {successes}\n"
            f"Published: {published}\n"
            f"Transcription failures: {transcription_failures}\n"
            f"Publish failures: {publish_failures}"
        )
    return (
        f"Processed {total} recording(s).\n\n"
        f"Succeeded: {successes}\n"
        f"Failed: {transcription_failures}\n\n"
        "Successful meetings are now visible in Meetings as Unpublished."
    )
