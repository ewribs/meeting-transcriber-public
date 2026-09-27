from __future__ import annotations

from typing import Any

from app_settings import (
    load_app_settings,
    save_app_settings,
)


BUILTIN_FAVORITES = [
    {
        "id": "builtin.executive_summary",
        "title": "Executive Summary",
        "prompt": (
            "Give me an executive summary of the selected context, "
            "focusing on the most important developments and decisions."
        ),
        "built_in": True,
    },
    {
        "id": "builtin.decisions",
        "title": "Decisions",
        "prompt": (
            "What decisions were made across this context? "
            "Separate confirmed decisions from items still under discussion."
        ),
        "built_in": True,
    },
    {
        "id": "builtin.my_actions",
        "title": "My Actions",
        "prompt": (
            "What actions, commitments, or follow-ups do I own "
            "across this context?"
        ),
        "built_in": True,
    },
    {
        "id": "builtin.open_questions",
        "title": "Open Questions",
        "prompt": (
            "What remains unresolved or unanswered across this context?"
        ),
        "built_in": True,
    },
    {
        "id": "builtin.changes",
        "title": "Changes",
        "prompt": (
            "Compare the latest meeting with the immediately previous "
            "meeting and tell me what changed since last time."
        ),
        "built_in": True,
        "category": "changes",
    },
    {
        "id": "builtin.risks_blockers",
        "title": "Risks / Blockers",
        "prompt": (
            "What risks, blockers, dependencies, or constraints "
            "were discussed across this context?"
        ),
        "built_in": True,
    },
    {
        "id": "builtin.boss_1v1_prep",
        "title": "Boss 1:1 Prep",
        "prompt": (
            "Prepare me for my 1:1 with my boss using the selected context. "
            "Review every selected meeting independently before synthesizing. "
            "Treat likely staff 1:1 meetings as the primary source of staff-level "
            "issues, and use only genuinely non-1:1 selected meetings for ad-hoc "
            "signals.\n\n"
            "Organize the brief into these sections:\n"
            "1. What needs attention now — urgent, time-sensitive, or blocked items.\n"
            "2. Open staff items — unresolved commitments, decisions, follow-ups, "
            "or questions from recent 1:1s, grouped by staff member/meeting.\n"
            "3. Themes across the team — include a theme only when at least two "
            "distinct meetings support it, and name the supporting meetings.\n"
            "4. Ad-hoc signals — use only selected meetings that are not staff 1:1s. "
            "If none are selected, write 'None identified.'\n"
            "5. Sensitive / escalation topics — items that may require careful handling, "
            "leadership awareness, or escalation.\n"
            "6. Decisions or help I need from my boss — include only items with explicit "
            "evidence that leadership approval, a decision, escalation, intervention, "
            "prioritization, sponsorship, guidance, or an exception is needed. Do not "
            "turn ordinary open work or staff follow-ups into boss asks.\n"
            "7. My commitments — include only commitments supported as belonging to me. "
            "Never include a staff member's own commitments here. If my identity cannot "
            "be established safely from the selected sources, write 'None identified.'\n"
            "8. Worth mentioning — include only genuine positive progress or wins such "
            "as completed milestones, measurable savings, successful negotiations, "
            "resolved risks, or delivered outcomes. Do not present challenges or "
            "unfinished work as wins.\n\n"
            "Be concise but specific. Cite the meeting date/title beside substantive items. "
            "Do not infer that an item is resolved just because it was not mentioned later. "
            "Distinguish confirmed facts from unclear status. If a section has nothing "
            "supported by the selected meetings, write 'None identified.'"
        ),
        "built_in": True,
        "category": "recipe",
    },
    {
        "id": "builtin.prepare_next",
        "title": "Prepare for Next Meeting",
        "prompt": (
            "Prepare me for the next meeting using this context. "
            "Summarize what I should remember, outstanding commitments, "
            "unresolved questions, and likely follow-ups."
        ),
        "built_in": True,
    },
]


def _with_category(
    item: dict,
) -> dict:
    enriched = dict(item)
    enriched.setdefault(
        "category",
        "favorite",
    )
    return enriched


def _clean_custom_favorite(
    item: Any,
) -> dict | None:
    if not isinstance(item, dict):
        return None

    favorite_id = str(
        item.get("id", "")
    ).strip()
    title = str(
        item.get("title", "")
    ).strip()
    prompt = str(
        item.get("prompt", "")
    ).strip()

    if (
        not favorite_id
        or not title
        or not prompt
        or favorite_id.startswith("builtin.")
    ):
        return None

    return {
        "id": favorite_id,
        "title": title,
        "prompt": prompt,
        "built_in": False,
        "category": "favorite",
    }


def normalize_custom_favorites(
    raw: Any,
) -> list[dict]:
    if not isinstance(raw, list):
        return []

    cleaned: list[dict] = []
    seen: set[str] = set()

    for item in raw:
        favorite = _clean_custom_favorite(
            item
        )

        if favorite is None:
            continue

        favorite_id = favorite["id"]

        if favorite_id in seen:
            continue

        seen.add(favorite_id)
        cleaned.append(favorite)

    return cleaned


def load_prompt_favorites() -> list[dict]:
    settings = load_app_settings()

    custom = normalize_custom_favorites(
        settings.get("prompt_favorites")
    )

    return [
        *[
            _with_category(item)
            for item in BUILTIN_FAVORITES
        ],
        *custom,
    ]


def save_custom_prompt_favorites(
    custom_favorites: Any,
) -> list[dict]:
    custom = normalize_custom_favorites(
        custom_favorites
    )

    settings = load_app_settings()
    settings["prompt_favorites"] = [
        {
            "id": item["id"],
            "title": item["title"],
            "prompt": item["prompt"],
        }
        for item in custom
    ]
    save_app_settings(settings)

    return [
        *[
            _with_category(item)
            for item in BUILTIN_FAVORITES
        ],
        *custom,
    ]
