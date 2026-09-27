from __future__ import annotations

from copy import deepcopy
import re


_STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "before",
    "but",
    "can",
    "could",
    "for",
    "from",
    "give",
    "has",
    "have",
    "how",
    "into",
    "just",
    "meeting",
    "meetings",
    "need",
    "next",
    "our",
    "please",
    "prepare",
    "should",
    "tell",
    "that",
    "the",
    "their",
    "them",
    "then",
    "these",
    "they",
    "things",
    "this",
    "those",
    "top",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
    "you",
}

_HISTORY_REQUEST_TERMS = (
    "all history",
    "entire history",
    "full history",
    "historical",
    "history",
    "over time",
    "timeline",
    "trend",
    "trends",
    "evolved",
    "evolution",
    "changed since",
    "compare over",
    "from the beginning",
    "since the beginning",
)

_COMPREHENSIVE_REQUEST_TERMS = (
    "comprehensive",
    "everything",
    "all topics",
    "all meetings",
    "complete summary",
    "full summary",
)

_DEFAULT_HISTORY_LIMIT = 2
_MATCHED_HISTORY_LIMIT = 6
_RECENT_DECISION_LIMIT = 8


def query_terms(user_prompt: str) -> set[str]:
    words = re.findall(
        r"[a-z0-9][a-z0-9._-]*",
        user_prompt.lower(),
    )

    return {
        word
        for word in words
        if len(word) >= 3
        and word not in _STOP_WORDS
    }


def _text_matches_terms(
    value: object,
    query_terms: set[str],
) -> bool:
    if not query_terms:
        return False

    text = str(value or "").lower()

    return any(
        term in text
        for term in query_terms
    )


def _topic_matches_query(
    topic: dict,
    query_terms: set[str],
) -> bool:
    searchable = " ".join(
        str(topic.get(field, ""))
        for field in (
            "topic_key",
            "topic",
            "summary",
        )
    )

    return _text_matches_terms(
        searchable,
        query_terms,
    )


def _history_matches_query(
    history: list[dict],
    query_terms: set[str],
) -> bool:
    for entry in history:
        searchable = " ".join(
            str(entry.get(field, ""))
            for field in (
                "topic",
                "summary",
                "status",
            )
        )

        if _text_matches_terms(
            searchable,
            query_terms,
        ):
            return True

    return False


def is_broad_history_request(
    user_prompt: str,
) -> bool:
    prompt = user_prompt.lower()

    return any(
        term in prompt
        for term in (
            *_HISTORY_REQUEST_TERMS,
            *_COMPREHENSIVE_REQUEST_TERMS,
        )
    )


def prepare_query_memory(
    user_prompt: str,
    merged_memory: dict,
) -> dict:
    """
    Return a smaller model-facing copy of merged meeting memory.

    The original merged memory remains untouched and continues to be
    used by deterministic grounded rendering. Broad historical or
    comprehensive requests deliberately keep the full memory so this
    optimization does not silently narrow the user's requested scope.
    """

    prepared = deepcopy(
        merged_memory
    )

    if is_broad_history_request(
        user_prompt
    ):
        return prepared

    query_term_set = query_terms(
        user_prompt
    )

    active_topic_keys = {
        topic.get("topic_key")
        for topic in prepared.get(
            "active_topics",
            [],
        )
        if isinstance(topic, dict)
        and topic.get("topic_key")
    }

    anchor_topic_keys = {
        topic.get("topic_key")
        for topic in prepared.get(
            "anchor_topics",
            [],
        )
        if isinstance(topic, dict)
        and topic.get("topic_key")
    }

    matched_topic_keys = set()

    for collection_name in (
        "active_topics",
        "anchor_topics",
        "supporting_topics",
        "recurring_topics",
    ):
        for topic in prepared.get(
            collection_name,
            [],
        ):
            if not isinstance(
                topic,
                dict,
            ):
                continue

            if _topic_matches_query(
                topic,
                query_term_set,
            ):
                topic_key = topic.get(
                    "topic_key"
                )

                if topic_key:
                    matched_topic_keys.add(
                        topic_key
                    )

    topic_history = prepared.get(
        "topic_history",
        {},
    )

    pruned_history = {}

    for topic_key, history in (
        topic_history.items()
    ):
        if not isinstance(
            history,
            list,
        ):
            continue

        history_matches = (
            _history_matches_query(
                history,
                query_term_set,
            )
        )

        if history_matches:
            matched_topic_keys.add(
                topic_key
            )

        if (
            topic_key
            not in active_topic_keys
            and topic_key
            not in matched_topic_keys
        ):
            continue

        limit = (
            _MATCHED_HISTORY_LIMIT
            if (
                topic_key
                in matched_topic_keys
            )
            else _DEFAULT_HISTORY_LIMIT
        )

        if topic_key in anchor_topic_keys:
            limit = max(
                limit,
                _DEFAULT_HISTORY_LIMIT,
            )

        pruned_history[topic_key] = (
            history[-limit:]
        )

    prepared["topic_history"] = (
        pruned_history
    )

    decisions = prepared.get(
        "decisions",
        [],
    )

    if isinstance(decisions, list):
        matched_decisions = [
            item
            for item in decisions
            if _text_matches_terms(
                item,
                query_term_set,
            )
        ]

        recent_decisions = (
            decisions[
                -_RECENT_DECISION_LIMIT:
            ]
        )

        kept_decisions = []
        seen = set()

        for item in (
            matched_decisions
            + recent_decisions
        ):
            marker = repr(item)

            if marker in seen:
                continue

            seen.add(marker)
            kept_decisions.append(item)

        prepared["decisions"] = (
            kept_decisions
        )

    return prepared
