from query.grounding import (
    associate_follow_ups_with_topics,
    associate_open_questions_with_topics,
)
from merge_meeting_memories import merge_memories


def build_meeting_context(
    meeting_memories: list[tuple[str, dict]],
    selected: list[dict],
    topic: str | None = None,
) -> dict:
    if not meeting_memories:
        raise ValueError(
            "No meetings matched the supplied selection."
        )

    merged_memory = merge_memories(
        meeting_memories
    )

    if topic:
        topic_term = topic.lower()

        matching_topic_keys = {
            item.get("topic_key")
            for item in merged_memory[
                "current_topics"
            ]
            if topic_term in (
                f"{item.get('topic_key', '')} "
                f"{item.get('topic', '')} "
                f"{item.get('summary', '')}"
            ).lower()
        }

        merged_memory["current_topics"] = [
            item
            for item in merged_memory[
                "current_topics"
            ]
            if item.get("topic_key")
            in matching_topic_keys
        ]

        merged_memory["topic_history"] = {
            topic_key: history
            for topic_key, history
            in merged_memory[
                "topic_history"
            ].items()
            if topic_key
            in matching_topic_keys
        }

    latest_meeting = meeting_memories[-1][0]

    anchor_meeting = latest_meeting

    if selected:
        highest_weight = max(
            item["relevance_weight"]
            for item in selected
        )

        anchor_candidates = [
            item
            for item in selected
            if item["relevance_weight"]
            == highest_weight
        ]

        anchor_meeting = max(
            anchor_candidates,
            key=lambda item: (
                item["meeting_run"]
            ),
        )["meeting_run"]

    selected_by_run = {
        item["meeting_run"]: item
        for item in selected
    }

    def meeting_label(
        meeting_run: str,
    ) -> str:
        item = selected_by_run.get(
            meeting_run
        )

        if not item:
            return meeting_run

        meeting_date = (
            item["meeting_run"][:10]
        )

        return (
            f"{meeting_date} | "
            f"{item['display_title']}"
        )

    supporting_meetings = [
        meeting_run
        for meeting_run, _
        in meeting_memories
        if meeting_run != anchor_meeting
    ]

    anchor_memory = next(
        memory
        for meeting_run, memory
        in meeting_memories
        if meeting_run == anchor_meeting
    )

    anchor_topic_keys = {
        item.get("topic_key")
        for item
        in anchor_memory.get(
            "topics",
            [],
        )
        if isinstance(item, dict)
    }

    merged_memory["current_topics"] = [
        item
        for item
        in merged_memory["current_topics"]
        if item.get("status") != "closed"
    ]

    merged_memory["open_questions"] = [
        item
        for item
        in merged_memory["open_questions"]
        if item.get("meeting")
        == anchor_meeting
    ]

    merged_memory["follow_ups"] = [
        item
        for item
        in merged_memory["follow_ups"]
        if item.get("meeting")
        == anchor_meeting
    ]

    merged_memory["commitments"] = [
        item
        for item
        in merged_memory["commitments"]
        if item.get("meeting")
        == anchor_meeting
    ]

    merged_memory["topic_history"] = {
        topic_key: history
        for topic_key, history
        in merged_memory[
            "topic_history"
        ].items()
        if len(history) >= 2
    }

    active_topics = [
        item
        for item
        in merged_memory["current_topics"]
        if (
            item.get("topic_key")
            in anchor_topic_keys
            or item.get(
                "seen_in_latest_meeting"
            )
            or item.get("recurring")
        )
    ]

    def topic_priority(
        item: dict,
    ) -> tuple[int, int, int]:
        topic_key = item.get(
            "topic_key"
        )

        return (
            1
            if topic_key
            in anchor_topic_keys
            else 0,
            1
            if item.get("recurring")
            else 0,
            1
            if item.get(
                "seen_in_latest_meeting"
            )
            else 0,
        )

    active_topics = sorted(
        active_topics,
        key=topic_priority,
        reverse=True,
    )

    anchor_topics = [
        item
        for item in active_topics
        if item.get("topic_key")
        in anchor_topic_keys
    ]

    (
        topic_open_questions,
        unassigned_open_questions,
    ) = associate_open_questions_with_topics(
        merged_memory["open_questions"],
        anchor_topics,
    )

    merged_memory[
        "topic_open_questions"
    ] = topic_open_questions

    merged_memory[
        "unassigned_open_questions"
    ] = unassigned_open_questions

    del merged_memory["open_questions"]

    (
        topic_follow_ups,
        unassigned_follow_ups,
    ) = associate_follow_ups_with_topics(
        merged_memory["follow_ups"],
        anchor_topics,
    )

    merged_memory[
        "topic_follow_ups"
    ] = topic_follow_ups

    merged_memory[
        "unassigned_follow_ups"
    ] = unassigned_follow_ups

    del merged_memory["follow_ups"]

    supporting_topics = [
        item
        for item in active_topics
        if (
            item.get("topic_key")
            not in anchor_topic_keys
            and item.get(
                "seen_in_latest_meeting"
            )
        )
    ]

    recurring_topics = [
        item
        for item in active_topics
        if item.get("recurring")
    ]

    merged_memory["anchor_meeting"] = (
        anchor_meeting
    )

    merged_memory["active_topics"] = (
        active_topics
    )

    merged_memory["anchor_topics"] = (
        anchor_topics
    )

    merged_memory["supporting_topics"] = (
        supporting_topics
    )

    merged_memory["recurring_topics"] = (
        recurring_topics
    )

    del merged_memory["current_topics"]

    return {
        "merged_memory": merged_memory,
        "meeting_memories": list(meeting_memories),
        "selected_meetings": [
            dict(item)
            for item in selected
        ],
        "topic_filter": topic,
        "anchor_meeting": anchor_meeting,
        "anchor_label": meeting_label(
            anchor_meeting
        ),
        "supporting_meetings": (
            supporting_meetings
        ),
        "supporting_labels": [
            meeting_label(meeting_run)
            for meeting_run
            in supporting_meetings
        ],
        "meeting_count": len(
            meeting_memories
        ),
    }
