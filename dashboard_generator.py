import re
from datetime import datetime
from pathlib import Path
import html
import json


def format_meeting_name(run_name: str) -> str:
    try:
        date_part, time_part, title = run_name.split("_", 2)

        meeting_dt = datetime.strptime(
            f"{date_part}_{time_part}",
            "%Y-%m-%d_%H%M",
        )

        # Remove trailing MMDDYY from the original recording name.
        title = re.sub(
            r"\d{6}$",
            "",
            title,
        )

        title = title.replace("_", " ")

        # Add spaces between CamelCase words.
        title = re.sub(
            r"(?<=[a-z])(?=[A-Z])",
            " ",
            title,
        )

        # Preserve acronyms such as ABC while separating the next word.
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

        return (
            f"{title.strip()} — "
            f"{meeting_dt.strftime('%b %-d, %Y %-I:%M %p')}"
        )

    except ValueError:
        return run_name


def get_summary_preview(
    meeting_dir: Path,
    max_length: int = 160,
) -> str:
    summary_path = (
        meeting_dir / "meeting_summary.md"
    )

    if not summary_path.exists():
        return ""

    for line in summary_path.read_text(
        encoding="utf-8",
    ).splitlines():
        line = line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if len(line) > max_length:
            return line[:max_length].rstrip() + "…"

        return line

    return ""


def get_meeting_date_label(
    run_name: str,
) -> str:
    try:
        date_part = run_name.split("_", 1)[0]

        meeting_date = datetime.strptime(
            date_part,
            "%Y-%m-%d",
        )

        return meeting_date.strftime(
            "%B %-d, %Y"
        )

    except ValueError:
        return "Unknown Date"


def format_meeting_datetime(
    run_name: str,
) -> str:
    try:
        date_part, time_part, _ = run_name.split(
            "_",
            2,
        )

        meeting_dt = datetime.strptime(
            f"{date_part}_{time_part}",
            "%Y-%m-%d_%H%M",
        )

        return meeting_dt.strftime(
            "%b %-d, %Y %-I:%M %p"
        )

    except ValueError:
        return ""


def build_meeting_dashboard(
    index_path: Path,
) -> Path:
    """
    Build a browser-based dashboard from meeting_index.json.
    """

    output_dir = index_path.parent

    meetings = json.loads(
        index_path.read_text(
            encoding="utf-8",
        )
    )

    rows = []

    current_date_label = None

    for meeting in meetings:
        run_name = meeting.get(
            "meeting_run",
            "Unknown",
        )

        display_title = meeting.get(
            "display_title",
        )

        if display_title:
            meeting_label = (
                f"{display_title} — "
                f"{format_meeting_datetime(run_name)}"
            )
        else:
            meeting_label = format_meeting_name(
                run_name
            )

        date_label = get_meeting_date_label(
            run_name,
        )

        if date_label != current_date_label:
            rows.append(
                f"""
                <tr class="date-group">
                    <td colspan="3">
                        {html.escape(date_label)}
                    </td>
                </tr>
                """
            )

            current_date_label = date_label

        meeting_dir = (
            output_dir / run_name
        )

        summary_preview = get_summary_preview(
            meeting_dir,
        )

        participants = meeting.get(
            "participants",
            [],
        )

        participant_label = ""

        if participants:
            participant_label = ", ".join(
                str(name)
                for name in participants
                if str(name).strip()
            )

        artifacts = meeting.get(
            "artifacts",
            {},
        )

        transcript = "-"

        if artifacts.get("transcript"):
            transcript = (
                f'<a class="utility-link" href="{html.escape(run_name)}/meeting_transcript.html">'
                "Open"
                "</a>"
            )

        onenote = "-"

        if artifacts.get("onenote_export"):
            onenote = (
                f'<a class="utility-link" href="{html.escape(run_name)}/exports/'
                f'OneNote_{html.escape(run_name)}.html">'
                "Open"
                "</a>"
            )

        rows.append(
            f"""
            <tr>
                <td>
                    <a class="meeting-link" href="{html.escape(run_name)}/meeting_summary.html">
                        {html.escape(meeting_label)}
                    </a>
                    <div class="meeting-participants">
                        {html.escape(participant_label)}
                    </div>
                    <div class="meeting-preview">
                        {html.escape(summary_preview)}
                    </div>
                </td>
                <td>{onenote}</td>
                <td>{transcript}</td>
            </tr>
            """
        )


    document = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">

<title>Meeting Transcriber Dashboard</title>

<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    margin: 40px;
}}

table {{
    border-collapse: collapse;
    width: 100%;
}}

th, td {{
    border: 1px solid #ccc;
    padding: 8px;
    text-align: left;
}}

th {{
    background: #eee;
}}

#meetingSearch {{
    width: 100%;
    max-width: 500px;
    padding: 10px 12px;
    margin-bottom: 16px;
    font-size: 16px;
    box-sizing: border-box;
}}

.meeting-link {{
    font-weight: 600;
    text-decoration: none;
}}

.meeting-link:hover {{
    text-decoration: underline;
}}

.utility-link {{
    font-size: 14px;
    text-decoration: none;
}}

.utility-link:hover {{
    text-decoration: underline;
}}

.meeting-participants {{
    margin-top: 4px;
    font-size: 13px;
    font-weight: 600;
    color: #444;
}}

.meeting-preview {{
    margin-top: 4px;
    font-size: 13px;
    color: #666;
    line-height: 1.35;
}}

.date-group td {{
    background: #f5f5f5;
    font-weight: 700;
    font-size: 14px;
    padding-top: 10px;
    padding-bottom: 10px;
}}

</style>

</head>

<body>

<h1>Meeting Transcriber Dashboard</h1>

<input
    type="text"
    id="meetingSearch"
    placeholder="Search meetings..."
    onkeyup="filterMeetings()"
>

<table>

<tr>
<th>Meeting</th>
<th>OneNote</th>
<th>Transcript</th>
</tr>

{"".join(rows)}

</table>

<script>
function filterMeetings() {{
    const input = document.getElementById("meetingSearch");
    const filter = input.value.toLowerCase();
    const rows = Array.from(
        document.querySelectorAll("tbody tr")
    );

    // First, filter the actual meeting rows.
    rows.forEach(function(row) {{
        // Date headers have one cell spanning the table.
        if (row.cells.length === 1) {{
            return;
        }}

        const meeting = row.cells[0].textContent.toLowerCase();

        if (meeting.includes(filter)) {{
            row.style.display = "";
        }} else {{
            row.style.display = "none";
        }}
    }});

    // Then hide date headers that have no visible meetings.
    rows.forEach(function(row, index) {{
        if (row.cells.length !== 1) {{
            return;
        }}

        let hasVisibleMeeting = false;

        for (let i = index + 1; i < rows.length; i++) {{
            const nextRow = rows[i];

            // Reached the next date header.
            if (nextRow.cells.length === 1) {{
                break;
            }}

            if (nextRow.style.display !== "none") {{
                hasVisibleMeeting = true;
                break;
            }}
        }}

        row.style.display = hasVisibleMeeting ? "" : "none";
    }});
}}
</script>

</body>
</html>
"""

    dashboard_path = (
        output_dir / "meeting_index.html"
    )

    dashboard_path.write_text(
        document,
        encoding="utf-8",
    )

    return dashboard_path
