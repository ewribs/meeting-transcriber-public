from __future__ import annotations

import json

from query.pruning import (
    is_broad_history_request,
    query_terms,
)


DEFAULT_MAX_QUERY_MEETINGS = 8
RECENT_FALLBACK_MEETINGS = 2


def _meeting_search_text(
    memory: dict,
    selected_item: dict,
) -> str:
    participants = selected_item.get(
        "participants",
        [],
    )

    metadata_text = " ".join(
        [
            str(
                selected_item.get(
                    "meeting_run",
                    "",
                )
            ),
            str(
                selected_item.get(
                    "display_title",
                    "",
                )
            ),
            " ".join(
                str(person)
                for person in participants
            ),
        ]
    )

    return (
        metadata_text
        + " "
        + json.dumps(
            memory,
            ensure_ascii=False,
            default=str,
        )
    ).lower()


def select_query_meetings(
    user_prompt: str,
    meeting_memories: list[tuple[str, dict]],
    selected: list[dict],
    max_meetings: int = DEFAULT_MAX_QUERY_MEETINGS,
) -> tuple[
    list[tuple[str, dict]],
    list[dict],
]:
    """
    Select a bounded meeting-level working set for model inference.

    Session membership is not changed. Broad historical/comprehensive
    requests deliberately keep every meeting so later chunking can
    handle those requests without silently narrowing their scope.
    """

    if (
        len(meeting_memories) <= max_meetings
        or is_broad_history_request(
            user_prompt
        )
    ):
        return (
            list(meeting_memories),
            [dict(item) for item in selected],
        )

    terms = query_terms(
        user_prompt
    )

    selected_by_run = {
        item.get("meeting_run"): item
        for item in selected
        if item.get("meeting_run")
    }

    scored = []

    for recency_index, (
        meeting_run,
        memory,
    ) in enumerate(meeting_memories):
        selected_item = dict(
            selected_by_run.get(
                meeting_run,
                {
                    "meeting_run": meeting_run,
                    "display_title": meeting_run,
                    "relevance_weight": 1,
                },
            )
        )

        searchable = _meeting_search_text(
            memory,
            selected_item,
        )

        matched_terms = {
            term
            for term in terms
            if term in searchable
        }

        scored.append(
            {
                "meeting_run": meeting_run,
                "memory": memory,
                "selected": selected_item,
                "match_count": len(
                    matched_terms
                ),
                "recency_index": (
                    recency_index
                ),
            }
        )

    if not terms:
        chosen = scored[
            -max_meetings:
        ]
    else:
        matched = [
            item
            for item in scored
            if item["match_count"] > 0
        ]

        matched.sort(
            key=lambda item: (
                item["match_count"],
                item["recency_index"],
            ),
            reverse=True,
        )

        relevance_slots = max(
            max_meetings
            - RECENT_FALLBACK_MEETINGS,
            0,
        )

        chosen = matched[
            :relevance_slots
        ]

        chosen_runs = {
            item["meeting_run"]
            for item in chosen
        }

        for item in reversed(scored):
            if (
                len(chosen)
                >= max_meetings
            ):
                break

            if (
                item["meeting_run"]
                in chosen_runs
            ):
                continue

            chosen.append(item)
            chosen_runs.add(
                item["meeting_run"]
            )

    chosen = sorted(
        chosen,
        key=lambda item: item[
            "recency_index"
        ],
    )

    chosen_memories = []
    chosen_selected = []

    for item in chosen:
        chosen_memories.append(
            (
                item["meeting_run"],
                item["memory"],
            )
        )

        selected_item = dict(
            item["selected"]
        )

        if item["match_count"] > 0:
            selected_item[
                "relevance_weight"
            ] = (
                int(
                    selected_item.get(
                        "relevance_weight",
                        1,
                    )
                )
                + (
                    item["match_count"]
                    * 10
                )
            )

        chosen_selected.append(
            selected_item
        )

    return (
        chosen_memories,
        chosen_selected,
    )
