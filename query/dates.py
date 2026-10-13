import re

from datetime import date, timedelta


def resolve_query_dates(
    user_prompt: str,
) -> tuple[str, str]:
    today_date = date.today()
    today = today_date.isoformat()

    days_until_monday = (
        7 - today_date.weekday()
    ) % 7

    if days_until_monday == 0:
        days_until_monday = 7

    next_monday = (
        today_date
        + timedelta(days=days_until_monday)
    ).isoformat()

    resolved_user_prompt = re.sub(
        r"\bnext monday\b",
        f"Monday, {next_monday}",
        user_prompt,
        flags=re.IGNORECASE,
    )

    days_until_next_monday = (
        7 - today_date.weekday()
    )

    next_week_start = (
        today_date
        + timedelta(
            days=days_until_next_monday
        )
    )

    next_week_end = (
        next_week_start
        + timedelta(days=6)
    )

    relative_replacements = {
        r"\btoday\b": today_date.isoformat(),
        r"\btomorrow\b": (
            today_date + timedelta(days=1)
        ).isoformat(),
        r"\bnext week\b": (
            f"the week of "
            f"{next_week_start.isoformat()} "
            f"through "
            f"{next_week_end.isoformat()}"
        ),
    }

    for pattern, replacement in (
        relative_replacements.items()
    ):
        resolved_user_prompt = re.sub(
            pattern,
            replacement,
            resolved_user_prompt,
            flags=re.IGNORECASE,
        )

    return (
        resolved_user_prompt,
        today,
    )
