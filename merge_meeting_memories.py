from pathlib import Path
import argparse
import json


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


def merge_memories(
    meeting_memories: list[tuple[str, dict]],
) -> dict:
    """
    Merge chronological meeting memories.

    Later topic state supersedes earlier topic state
    when topic_key matches.
    """

    merged_topics = {}
    topic_history = {}

    latest_meeting_label = (
        meeting_memories[-1][0]
        if meeting_memories
        else None
    )

    commitments = []
    decisions = []
    open_questions = []
    follow_ups = []

    for meeting_label, memory in meeting_memories:
        for topic in memory.get(
            "topics",
            [],
        ):
            if not isinstance(
                topic,
                dict,
            ):
                continue

            topic_key = str(
                topic.get(
                    "topic_key",
                    "",
                )
            ).strip()

            if not topic_key:
                continue

            history_entry = {
                "meeting": meeting_label,
                "topic": topic.get(
                    "topic",
                    "",
                ),
                "status": topic.get(
                    "status",
                    "unclear",
                ),
                "summary": topic.get(
                    "summary",
                    "",
                ),
            }

            topic_history.setdefault(
                topic_key,
                [],
            ).append(
                history_entry
            )

            merged_topics[
                topic_key
            ] = {
                "topic_key": topic_key,
                "topic": topic.get(
                    "topic",
                    topic_key,
                ),
                "status": topic.get(
                    "status",
                    "unclear",
                ),
                "summary": topic.get(
                    "summary",
                    "",
                ),
                "latest_meeting": (
                    meeting_label
                ),
            }

        for commitment in memory.get(
            "commitments",
            [],
        ):
            if not isinstance(
                commitment,
                dict,
            ):
                continue

            commitments.append(
                {
                    "meeting": meeting_label,
                    **commitment,
                }
            )

        for decision in memory.get(
            "decisions",
            [],
        ):
            if isinstance(decision, dict):
                decision_text = str(
                    decision.get(
                        "decision",
                        "",
                    )
                ).strip()
                evidence_text = str(
                    decision.get(
                        "evidence",
                        "",
                    )
                ).strip()
            else:
                decision_text = str(decision).strip()
                evidence_text = ""

            if not decision_text:
                continue

            merged_decision = {
                "meeting": meeting_label,
                "decision": decision_text,
            }

            if evidence_text:
                merged_decision[
                    "evidence"
                ] = evidence_text

            decisions.append(
                merged_decision
            )

        for question in memory.get(
            "open_questions",
            [],
        ):
            open_questions.append(
                {
                    "meeting": meeting_label,
                    "question": question,
                }
            )

        for follow_up in memory.get(
            "follow_ups",
            [],
        ):
            follow_ups.append(
                {
                    "meeting": meeting_label,
                    "follow_up": follow_up,
                }
            )

    for topic_key, topic in merged_topics.items():
        history = topic_history.get(
            topic_key,
            [],
        )

        topic["occurrence_count"] = len(
            history
        )

        topic["recurring"] = (
            len(history) >= 2
        )

        topic["seen_in_latest_meeting"] = (
            topic.get(
                "latest_meeting"
            )
            == latest_meeting_label
        )

    return {
        "current_topics": list(
            merged_topics.values()
        ),
        "topic_history": topic_history,
        "commitments": commitments,
        "decisions": decisions,
        "open_questions": open_questions,
        "follow_ups": follow_ups,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Merge cached meeting memories "
            "chronologically."
        ),
    )

    parser.add_argument(
        "meeting_dirs",
        nargs="+",
        type=Path,
    )

    args = parser.parse_args()

    meeting_memories = []

    for meeting_dir in args.meeting_dirs:
        meeting_memories.append(
            load_memory(
                meeting_dir
            )
        )

    merged = merge_memories(
        meeting_memories
    )

    print(
        json.dumps(
            merged,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
