"""
Meeting Recovery Utility

Provides tools for rebuilding outputs from an existing
meeting run without rerunning Whisper transcription.
"""

import markdown

from pathlib import Path

from config import OUTPUT_DIR

from metadata import create_meeting_metadata

from pipeline import (
    run_ai_cleanup,
    run_meeting_summary,
    export_onenote_summary,
    complete_post_summary_artifacts,
)



def refresh_metadata(run_dir):
    metadata_path = create_meeting_metadata(
        run_dir=run_dir,
    )

    print(
        f"Metadata updated: {metadata_path}"
    )


def resume_from_existing_summary(run_dir):
    """Finish a failed run without repeating Whisper, cleanup, or summary."""

    run_dir = Path(run_dir)
    cleaned_path = run_dir / "meeting_transcript_cleaned.md"
    summary_path = run_dir / "meeting_summary.md"
    transcript_path = run_dir / "meeting_transcript.md"

    required_paths = (
        cleaned_path,
        summary_path,
        transcript_path,
    )
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Cannot resume after summary; missing: "
            + ", ".join(str(path) for path in missing)
        )

    cleaned_transcript = cleaned_path.read_text(encoding="utf-8")
    meeting_summary = summary_path.read_text(encoding="utf-8")
    transcript_markdown = transcript_path.read_text(encoding="utf-8")

    return complete_post_summary_artifacts(
        run_dir=run_dir,
        meeting_summary=meeting_summary,
        cleaned_transcript=cleaned_transcript,
        transcript_html=markdown.markdown(transcript_markdown),
    )

def list_runs():
    """
    Return timestamped meeting run directories.
    """

    runs = sorted(
        [
            d for d in OUTPUT_DIR.iterdir()
            if d.is_dir()
        ],
        reverse=True,
    )

    return runs


def choose_run(runs):

    print()
    print("Available Meeting Runs")
    print("----------------------")

    for number, run in enumerate(runs, start=1):
        print(f"{number:2d}) {run.name}")

    print()

    while True:

        choice = input("Select meeting: ")

        try:

            index = int(choice) - 1

            if 0 <= index < len(runs):
                return runs[index]

        except ValueError:
            pass

        print("Invalid selection.")


def show_menu():

    print()
    print("Recovery Options")
    print("----------------")

    print("1) Rebuild Transcript HTML")
    print("2) Rebuild Summary HTML")
    print("3) Re-run AI Cleanup")
    print("4) Re-run Meeting Summary")
    print("5) Rebuild Everything After Whisper")
    print("6) Export OneNote Summary")
    print("7) Resume From Existing Transcript and Summary")
    print("0) Exit")

    print()

    return input("Selection: ")


def main():

    runs = list_runs()

    if not runs:
        print("No completed meeting runs found.")
        return

    run = choose_run(runs)

    print()
    print(f"Selected: {run.name}")

    selection = show_menu()

    print()

    if selection == "3":

        print("Running AI transcript cleanup...")
        print()

        cleaned_transcript, cleaned_path = run_ai_cleanup(
            run_dir=run,
        )

        print()
        print(f"Finished: {cleaned_path}")

        refresh_metadata(run)

    elif selection == "4":

        print("Running meeting summary...")
        print()

        meeting_summary, summary_html, summary_path, summary_html_path = (
            run_meeting_summary(
                run_dir=run,
            )
        )

        print()
        print(f"Summary saved: {summary_path}")
        print(f"Summary HTML saved: {summary_html_path}")

        refresh_metadata(run)

    elif selection == "5":

        print("Rebuilding everything after Whisper...")
        print()

        cleaned_transcript, cleaned_path = run_ai_cleanup(
            run_dir=run,
        )

        (
            meeting_summary,
            summary_html,
            summary_path,
            summary_html_path,
        ) = run_meeting_summary(
            run_dir=run,
            cleaned_transcript=cleaned_transcript,
        )

        completed = resume_from_existing_summary(run)

        print()
        print("Recovery complete.")
        print(f"Cleaned transcript: {cleaned_path}")
        print(f"Meeting summary: {summary_path}")
        print(
            "Transcript HTML: "
            f"{completed['transcript_html_path']}"
        )
        print(
            "Summary HTML: "
            f"{completed['summary_html_path']}"
        )
        print(f"Meeting memory: {completed['memory_path']}")

    elif selection == "6":

        print("Creating OneNote export...")
        print()

        output_path = export_onenote_summary(
            run_dir=run,
        )

        print()
        print("OneNote export complete.")
        print(f"Created: {output_path}")

        refresh_metadata(run)        

    elif selection == "7":

        print("Resuming from existing transcript and summary...")
        print()

        completed = resume_from_existing_summary(run)

        print()
        print("Recovery complete without rerunning Whisper or summary.")
        print(f"Meeting memory: {completed['memory_path']}")
        print(f"Meeting metadata: {completed['metadata_path']}")
        print(f"Summary HTML: {completed['summary_html_path']}")

    elif selection == "0":

        print("Cancelled.")

    else:

        print()
        print("That option hasn't been implemented yet.")

if __name__ == "__main__":
    main()
