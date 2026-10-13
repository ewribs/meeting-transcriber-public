
# Allow direct execution after repository reorganization.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse
import json
from pathlib import Path

from query.workbench import (
    configure_workbench,
)

from query.context import (
    build_meeting_context,
)

from query.chat import (
    run_query,
)

from query.session_context import (
    build_resumed_session_context,
)

from meeting_selector import (
    select_meetings,
)

from query.sessions import (
    delete_chat_session,
    list_chat_sessions,
    load_chat_session,
    rename_chat_session,
    save_chat_session,
    show_chat_session,
)

from config import ARCHIVE_DIR


def load_memory(
    meeting_dir: Path,
) -> tuple[str, dict]:
    memory_path = (
        meeting_dir
        / "meeting_memory.json"
    )

    if not memory_path.exists():
        raise FileNotFoundError(
            f"Meeting memory not found: "
            f"{memory_path}"
        )

    memory = json.loads(
        memory_path.read_text(
            encoding="utf-8",
        )
    )

    return (
        meeting_dir.name,
        memory,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Ask the local LLM a question using "
            "cached meeting memories."
        ),
    )

    parser.add_argument(
        "meeting_dirs",
        nargs="*",
        type=Path,
    )

    parser.add_argument(
        "--prompt",
    )

    parser.add_argument(
        "--person",
        type=str,
        help="Select meetings by participant name.",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        help="Only include meetings on or after YYYY-MM-DD.",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        help="Only include meetings on or before YYYY-MM-DD.",
    )

    parser.add_argument(
        "--topic",
        type=str,
        help="Only include meetings whose memory matches this topic.",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List selected meetings without running the LLM.",
    )

    parser.add_argument(
        "--select",
        action="store_true",
        help="Interactively choose from selected meetings.",
    )

    parser.add_argument(
        "--chat",
        action="store_true",
        help=(
            "Keep the selected meeting context loaded "
            "for multiple questions."
        ),
    )

    parser.add_argument(
        "--workbench",
        action="store_true",
        help=(
            "Interactively filter meetings, "
            "select context, and start chat."
        ),
    )

    parser.add_argument(
        "--session",
        type=str,
        help=(
            "Save chat context and history "
            "under this session name."
        ),
    )

    parser.add_argument(
        "--resume",
        type=str,
        help=(
            "Resume a previously saved chat session."
        ),
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Refresh a resumed session using "
            "its saved selection criteria."
        ),
    )

    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List saved meeting-memory chat sessions.",
    )

    parser.add_argument(
        "--delete-session",
        type=str,
        help="Delete a saved meeting-memory chat session.",
    )

    parser.add_argument(
        "--show-session",
        type=str,
        help="Show details for a saved meeting-memory chat session.",
    )

    parser.add_argument(
        "--rename-session",
        nargs=2,
        metavar=("OLD", "NEW"),
        help="Rename a saved meeting-memory chat session.",
    )

    args = parser.parse_args()

    
    if args.list_sessions:
        list_chat_sessions()
        return

    if args.delete_session:
        delete_chat_session(
            args.delete_session
        )
        return

    if args.show_session:
        show_chat_session(
            args.show_session
        )
        return

    if args.rename_session:
        old_name, new_name = (
            args.rename_session
        )

        rename_chat_session(
            old_name,
            new_name,
        )
        return

    if args.workbench:
        configure_workbench(
            args
        )

    if args.refresh and not args.resume:
        parser.error(
            "--refresh requires --resume"
        )

    selection_criteria = getattr(
        args,
        "selection_criteria",
        None,
    )

    resumed_session = None

    if args.resume:
        resumed_session = load_chat_session(
            args.resume
        )

        selection_criteria = resumed_session.get(
            "selection_criteria"
        )

        args.chat = True
        args.session = args.resume

    if (
        not args.list
        and not args.prompt
        and not args.select
        and not args.chat
    ):
        parser.error(
            "--prompt is required unless --list "
            "or --select, or --chat is used."
        )

    meeting_dirs = list(
        args.meeting_dirs
    )

    selected = []

    if resumed_session:
        try:
            resumed_context = (
                build_resumed_session_context(
                    resumed_session,
                    refresh=args.refresh,
                )
            )
        except ValueError as exc:
            parser.error(
                str(exc)
            )

        selection_criteria = (
            resumed_context[
                "selection_criteria"
            ]
        )

        selected = resumed_context[
            "selected"
        ]

        meeting_dirs.extend(
            resumed_context[
                "meeting_dirs"
            ]
        )

        if args.refresh:
            refresh_summary = (
                resumed_context[
                    "refresh_summary"
                ]
            )

            print()
            print("Session refresh:")
            print(
                f"- Added: "
                f"{refresh_summary['added']}"
            )
            print(
                f"- Removed: "
                f"{refresh_summary['removed']}"
            )
            print(
                f"- Unchanged: "
                f"{refresh_summary['unchanged']}"
            )
            print()

    if (
        args.person
        or args.start_date
        or args.end_date
        or args.topic
        or args.workbench
    ):

        selected = select_meetings(
            person=args.person,
            start_date=args.start_date,
            end_date=args.end_date,
            topic=args.topic,
        )

        meeting_dirs.extend(
            item["meeting_dir"]
            for item in selected
        )

    meeting_dirs = sorted(
        set(meeting_dirs),
        key=lambda path: path.name,
    )

    if args.list:
        if not meeting_dirs:
            print("No meetings matched.")
            return

        selected_by_path = {
            item["meeting_dir"]: item
            for item in selected
        }

        for meeting_dir in meeting_dirs:
            item = selected_by_path.get(
                meeting_dir
            )

            if item:
                meeting_date = item["meeting_run"][:10]

                print(
                    f"{meeting_date} | "
                    f"{item['display_title']} | "
                    f"participants: "
                    f"{item['participant_count']} | "
                    f"weight: "
                    f"{item['relevance_weight']}"
                )

            else:
                print(meeting_dir)

        return

    if args.select:
        if not meeting_dirs:
            print("No meetings matched.")
            return

        selected_by_path = {
            item["meeting_dir"]: item
            for item in selected
        }

        print()
        print("Selected Meetings")
        print("-----------------")

        numbered = []

        for number, meeting_dir in enumerate(
            meeting_dirs,
            start=1,
        ):
            item = selected_by_path.get(
                meeting_dir
            )

            if item:
                meeting_date = item["meeting_run"][:10]

                label = (
                    f"{meeting_date} | "
                    f"{item['display_title']} | "
                    f"participants: "
                    f"{item['participant_count']} | "
                    f"weight: "
                    f"{item['relevance_weight']}"
                )
            else:
                label = meeting_dir.name

            print(
                f"{number:2d}) {label}"
            )

            numbered.append(
                meeting_dir
            )

        print()
        choice = input(
            "Choose meetings "
            "(example: 1,3,5 or all): "
        ).strip()

        if choice.lower() != "all":
            try:
                indexes = {
                    int(value.strip()) - 1
                    for value in choice.split(",")
                    if value.strip()
                }
            except ValueError:
                print(
                    "Invalid selection. "
                    "Use numbers separated by commas, or 'all'."
                )
                return

            invalid_indexes = [
                index + 1
                for index in indexes
                if not (
                    0 <= index < len(numbered)
                )
            ]

            if invalid_indexes:
                print(
                    "Invalid meeting number(s): "
                    + ", ".join(
                        str(index)
                        for index
                        in sorted(invalid_indexes)
                    )
                )
                return

            meeting_dirs = [
                numbered[index]
                for index in sorted(indexes)
            ]

        if not meeting_dirs:
            print("No meetings selected.")
            return

        if not args.prompt:
            print()

            args.prompt = input(
                "Enter your question or request: "
            ).strip()

            if not args.prompt:
                print("No prompt entered.")
                return

        selected_paths = set(meeting_dirs)

        selected = [
            item
            for item in selected
            if item["meeting_dir"] in selected_paths
        ]

    meeting_memories = [
        load_memory(meeting_dir)
        for meeting_dir in meeting_dirs
    ]

    context = build_meeting_context(
        meeting_memories,
        selected,
        args.topic,
    )

    merged_memory = context[
        "merged_memory"
    ]

    print()
    print(
        f"Meetings in context: "
        f"{context['meeting_count']}"
    )
    print(
        f"Anchor meeting: "
        f"{context['anchor_label']}"
    )

    if context["supporting_labels"]:
        print("Supporting meetings:")

        for supporting_label in context[
            "supporting_labels"
        ]:
            print(
                f"  - {supporting_label}"
            )

    print()

    if args.chat:
        conversation_history = (
            resumed_session.get(
                "conversation_history",
                [],
            )
            if resumed_session
            else []
        )
        print()
        print(
            "Chat mode active. "
            "Type 'exit' or 'quit' to stop."
        )
        print()

        if args.prompt:
            result = run_query(
                args.prompt,
                merged_memory,
                conversation_history,
            )

            conversation_history.extend(
                [
                    {
                        "role": "user",
                        "content": args.prompt,
                    },
                    {
                        "role": "assistant",
                        "content": result,
                    },
                ]
            )

            if args.session:
                save_chat_session(
                    args.session,
                    meeting_dirs,
                    conversation_history,
                    selection_criteria,
                )

        while True:
            user_prompt = input(
                "You: "
            ).strip()

            if not user_prompt:
                continue

            if user_prompt.lower() in {
                "exit",
                "quit",
            }:
                if args.session:
                    session_path = save_chat_session(
                        args.session,
                        meeting_dirs,
                        conversation_history,
                        selection_criteria,
                    )

                    print(
                        f"Session saved: "
                        f"{session_path}"
                    )
                print("Chat ended.")
                break

            result = run_query(
                user_prompt,
                merged_memory,
                conversation_history,
            )

            conversation_history.extend(
                [
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                    {
                        "role": "assistant",
                        "content": result,
                    },
                ]
            )

            if args.session:
                save_chat_session(
                    args.session,
                    meeting_dirs,
                    conversation_history,
                )

    else:
        run_query(
            args.prompt,
            merged_memory,
        )


if __name__ == "__main__":
    main()
