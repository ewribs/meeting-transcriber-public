def collect_grounded_sections(
    user_prompt: str,
    merged_memory: dict,
    conversation_history: list[dict] | None = None,
) -> dict:
    action_terms = (
        "action",
        "actions",
        "commitment",
        "commitments",
        "follow-up",
        "follow up",
        "next step",
        "next steps",
        "what do i need to do",
    )

    question_terms = (
        "question",
        "questions",
        "open question",
        "open questions",
        "unresolved question",
        "unresolved questions",
        "what is unclear",
        "what's unclear",
        "what remains unclear",
        "what do we need to clarify",
    )

    prompt_lower = user_prompt.lower()

    include_actions = any(
        term in prompt_lower
        for term in action_terms
    )

    include_questions = any(
        term in prompt_lower
        for term in question_terms
    )
 
    topic_names = {
        topic.get("topic_key"): topic.get(
            "topic",
            topic.get("topic_key"),
        )
        for topic in merged_memory.get(
            "anchor_topics",
            [],
        )
    }

    topic_questions = []
    general_questions = []

    if include_questions:
        for topic_key, items in merged_memory.get(
            "topic_open_questions",
            {},
        ).items():
            questions = [
                str(
                    item.get(
                        "question",
                        "",
                    )
                ).strip()
                for item in items
            ]
            questions = [
                question
                for question in questions
                if question
            ]

            if not questions:
                continue

            topic_questions.append(
                {
                    "topic_key": topic_key,
                    "topic": topic_names.get(
                        topic_key,
                        topic_key,
                    ),
                    "questions": questions,
                }
            )

        general_questions = [
            str(
                item.get(
                    "question",
                    "",
                )
            ).strip()
            for item in merged_memory.get(
                "unassigned_open_questions",
                [],
            )
        ]
        general_questions = [
            question
            for question in general_questions
            if question
        ]

    commitments = []

    topic_follow_ups = []

    general_follow_ups = []

    if include_actions:
        commitments = [
            {
                "owner": item.get(
                    "owner",
                    "Unknown",
                ),
                "action": item.get(
                    "action",
                    "",
                ),
            }
            for item in merged_memory.get(
                "commitments",
                [],
            )
        ]

        for topic_key, items in merged_memory.get(
            "topic_follow_ups",
            {},
        ).items():
            topic_follow_ups.append(
                {
                    "topic_key": topic_key,
                    "topic": topic_names.get(
                        topic_key,
                        topic_key,
                    ),
                    "follow_ups": [
                        item.get(
                            "follow_up",
                            "",
                        )
                        for item in items
                    ],
                }
            )

        general_follow_ups = [
            item.get(
                "follow_up",
                "",
            )
            for item in merged_memory.get(
                "unassigned_follow_ups",
                [],
            )
        ]

    return {
        "topic_questions": topic_questions,
        "general_questions": general_questions,
        "commitments": commitments,
        "topic_follow_ups": topic_follow_ups,
        "general_follow_ups": general_follow_ups,
    }


def format_grounded_sections(
    user_prompt: str,
    merged_memory: dict,
    conversation_history: list[dict] | None = None,
) -> str:
    grounded = collect_grounded_sections(
        user_prompt,
        merged_memory,
        conversation_history,
    )

    topic_open_questions = grounded[
        "topic_questions"
    ]

    unassigned_open_questions = grounded[
        "general_questions"
    ]

    commitments = grounded[
        "commitments"
    ]

    topic_follow_ups = grounded[
        "topic_follow_ups"
    ]

    unassigned_follow_ups = grounded[
        "general_follow_ups"
    ]

    lines = []

    if (
        topic_open_questions
        or unassigned_open_questions
    ):
        lines.extend(
            [
                "## Grounded Open Questions",
                "",
            ]
        )

    if topic_open_questions:
        lines.extend(
            [
                "### Topic-Specific Open Questions",
                "",
            ]
        )

        for topic_group in topic_open_questions:
            topic_name = topic_group["topic"]
            items = topic_group["questions"]

            lines.append(
                f"**{topic_name}**"
            )

            for question in items:
                lines.append(
                    f"- {question}"
                )

            lines.append("")

    if unassigned_open_questions:
        lines.extend(
            [
                "### General / Unassigned Open Questions",
                "",
            ]
        )

        for question in (
            unassigned_open_questions
        ):
            lines.append(
                f"- {question}"
            )

        lines.append("")

    render_grounded_actions = bool(
        commitments
        or topic_follow_ups
        or unassigned_follow_ups
    )

    if render_grounded_actions:
        lines.extend(
            [
                "## Grounded Actions",
                "",
            ]
        )

    if commitments:
        lines.extend(
            [
                "### Commitments",
                "",
            ]
        )

        for item in commitments:
            owner = item.get(
                "owner",
                "Unknown",
            )

            action = item.get(
                "action",
                "",
            )

            lines.append(
                f"- {owner}: {action}"
            )

        lines.append("")

    if topic_follow_ups:
        lines.extend(
            [
                "### Topic-Specific Follow-Ups",
                "",
            ]
        )

        for topic_group in topic_follow_ups:
            topic_name = topic_group[
                "topic"
            ]

            items = topic_group[
                "follow_ups"
            ]

            lines.append(
                f"**{topic_name}**"
            )

            for follow_up in items:
                lines.append(
                    f"- {follow_up}"
                )

            lines.append("")

    if unassigned_follow_ups:
        lines.extend(
            [
                "### General / Unassigned Follow-Ups",
                "",
            ]
        )

        for follow_up in (
            unassigned_follow_ups
        ):
            lines.append(
                f"- {follow_up}"
            )

        lines.append("")

    return "\n".join(lines).rstrip()


def render_grounded_sections(
    user_prompt: str,
    merged_memory: dict,
    conversation_history: list[dict] | None = None,
) -> None:
    rendered = format_grounded_sections(
        user_prompt,
        merged_memory,
        conversation_history,
    )

    if rendered:
        print(rendered)
        print()
