from utils import TranscriptEntry

def format_timestamp(seconds: float) -> str:
    """
    Format seconds as [MM:SS] or [HH:MM:SS].
    """

    total_seconds = int(seconds)

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"[{hours:02}:{minutes:02}:{seconds:02}]"

    return f"[{minutes:02}:{seconds:02}]"

def format_transcript(
    entries: list[TranscriptEntry],
) -> str:
    """
    Format transcript entries into a human-readable transcript.
    """

    lines = [
        "# Meeting Transcript",
        "",
    ]

    for entry in entries:
        lines.append(
             f"{format_timestamp(entry.start)} **{entry.speaker}**"
        )
        lines.append("")
        lines.append(entry.text)
        lines.append("")
        lines.append("")

    return "\n".join(lines)

def format_transcript_html(
    entries: list[TranscriptEntry],
) -> str:
    """
    Format transcript entries as HTML.
    """

    sections = []

    for entry in entries:
        sections.append(
            f'<div class="speaker">'
            f'{format_timestamp(entry.start)} '
            f'{entry.speaker}'
            f'</div>'
        )

        sections.append(
            f'<p class="speech">{entry.text}</p>'
        )

    return "\n".join(sections)
