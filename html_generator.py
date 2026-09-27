"""
Build complete HTML documents for meeting transcripts and summaries.
"""


BASE_STYLES = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
        sans-serif;
    max-width: 900px;
    margin: 40px auto;
    padding: 0 24px;
    line-height: 1.6;
    color: #222;
}

h1 {
    margin-top: 0;
    margin-bottom: 28px;
}

h2 {
    margin-top: 32px;
    margin-bottom: 12px;
}

h3 {
    margin-top: 24px;
    margin-bottom: 10px;
}

ul {
    padding-left: 24px;
}
"""


TRANSCRIPT_STYLES = """
.speaker {
    font-weight: 700;
    margin-top: 28px;
    margin-bottom: 8px;
}

.speech {
    margin-top: 0;
}

hr {
    margin: 48px 0;
}
"""


def build_transcript_html(
    summary_html: str,
    transcript_html: str,
) -> str:
    """
    Build a complete HTML document containing the meeting summary
    followed by the timestamped transcript.
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >
    <title>Meeting Transcript</title>

    <style>
{BASE_STYLES}
{TRANSCRIPT_STYLES}
    </style>
</head>

<body>
    <h1>Meeting Summary</h1>

    <div class="summary">
        {summary_html}
    </div>

    <hr>

    <h1>Meeting Transcript</h1>

    {transcript_html}
</body>
</html>
"""


def build_summary_html(
    summary_html: str,
) -> str:
    """
    Build a complete HTML document containing only the meeting summary.
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >
    <title>Meeting Summary</title>

    <style>
{BASE_STYLES}
    </style>
</head>

<body>
    <div class="summary">
        {summary_html}
    </div>
</body>
</html>
"""


def build_onenote_html(
    meeting_title: str,
    summary_html: str,
    source_reference: str,
) -> str:
    """
    Build a standalone meeting summary intended for copying
    and pasting into OneNote.
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">

    <title>{meeting_title}</title>

    <style>
{BASE_STYLES}

.metadata {{
    margin-bottom: 30px;
    color: #555;
}}

.source-reference {{
    margin-top: 48px;
    padding-top: 16px;
    border-top: 1px solid #ccc;
    font-size: 0.9em;
    color: #666;
}}
    </style>
</head>

<body>
    <h1>{meeting_title}</h1>

    <div class="summary">
        {summary_html}
    </div>

    <div class="source-reference">
        Source: {source_reference}
    </div>
</body>
</html>
"""
