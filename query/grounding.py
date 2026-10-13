def associate_follow_ups_with_topics(
    follow_ups: list[dict],
    topics: list[dict],
) -> tuple[dict[str, list[dict]], list[dict]]:
    entity_topics = {}

    for topic in topics:
        topic_key = topic.get("topic_key")

        if not topic_key:
            continue

        entity = topic_key.split("_", 1)[0].lower()

        entity_topics.setdefault(
            entity,
            [],
        ).append(topic_key)

    topic_follow_ups = {}
    unassigned_follow_ups = []

    for item in follow_ups:
        text = item.get(
            "follow_up",
            "",
        ).lower()

        matches = []

        for entity, topic_keys in entity_topics.items():
            if entity in text:
                matches.extend(topic_keys)

        matches = list(set(matches))

        if len(matches) == 1:
            topic_key = matches[0]

            topic_follow_ups.setdefault(
                topic_key,
                [],
            ).append(item)
        else:
            unassigned_follow_ups.append(
                item
            )

    return (
        topic_follow_ups,
        unassigned_follow_ups,
    )


def associate_open_questions_with_topics(
    open_questions: list[dict],
    topics: list[dict],
) -> tuple[dict[str, list[dict]], list[dict]]:
    entity_topics = {}

    for topic in topics:
        topic_key = topic.get("topic_key")

        if not topic_key:
            continue

        entity = topic_key.split("_", 1)[0].lower()

        entity_topics.setdefault(
            entity,
            [],
        ).append(topic_key)

    topic_questions = {}
    unassigned_questions = []

    for item in open_questions:
        text = item.get(
            "question",
            "",
        ).lower()

        matches = []

        for entity, topic_keys in entity_topics.items():
            if entity in text:
                matches.extend(topic_keys)

        matches = list(set(matches))

        if len(matches) == 1:
            topic_key = matches[0]

            topic_questions.setdefault(
                topic_key,
                [],
            ).append(item)
        else:
            unassigned_questions.append(
                item
            )

    return (
        topic_questions,
        unassigned_questions,
    )
