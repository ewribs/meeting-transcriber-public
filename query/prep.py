from query.rendering import (
    collect_grounded_sections,
)


def build_meeting_prep(
    context: dict,
    max_priorities: int = 5,
) -> dict:
    merged_memory = context[
        "merged_memory"
    ]

    anchor_topic_keys = {
        topic.get("topic_key")
        for topic in merged_memory.get(
            "anchor_topics",
            [],
        )
    }

    supporting_topic_keys = {
        topic.get("topic_key")
        for topic in merged_memory.get(
            "supporting_topics",
            [],
        )
    }

    recurring_topic_keys = {
        topic.get("topic_key")
        for topic in merged_memory.get(
            "recurring_topics",
            [],
        )
    }

    priorities = []

    for topic in merged_memory.get(
        "active_topics",
        [],
    )[:max_priorities]:
        topic_key = topic.get(
            "topic_key"
        )

        priorities.append(
            {
                "topic_key": topic_key,
                "topic": topic.get(
                    "topic",
                    topic_key,
                ),
                "summary": topic.get(
                    "summary",
                    "",
                ),
                "status": topic.get(
                    "status",
                    "",
                ),
                "anchor": (
                    topic_key
                    in anchor_topic_keys
                ),
                "supporting": (
                    topic_key
                    in supporting_topic_keys
                ),
                "recurring": (
                    topic_key
                    in recurring_topic_keys
                ),
            }
        )

    grounded = collect_grounded_sections(
        (
            "Show actions, commitments, "
            "follow-ups, and open questions "
            "for meeting preparation."
        ),
        merged_memory,
    )

    return {
        "meeting_count": context[
            "meeting_count"
        ],
        "anchor_meeting": context[
            "anchor_meeting"
        ],
        "anchor_label": context[
            "anchor_label"
        ],
        "supporting_meetings": context[
            "supporting_meetings"
        ],
        "supporting_labels": context[
            "supporting_labels"
        ],
        "priorities": priorities,
        "questions": {
            "topic": grounded[
                "topic_questions"
            ],
            "general": grounded[
                "general_questions"
            ],
        },
        "actions": {
            "commitments": grounded[
                "commitments"
            ],
            "topic_follow_ups": grounded[
                "topic_follow_ups"
            ],
            "general_follow_ups": grounded[
                "general_follow_ups"
            ],
        },
    }
