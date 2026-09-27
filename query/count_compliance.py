from __future__ import annotations

import re


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_NUMBER_TOKEN = (
    r"(?:10|[1-9]|one|two|three|four|five|six|seven|eight|nine|ten)"
)

_COUNT_NOUN = (
    r"(?:things?|items?|points?|reasons?|priorities?|topics?|risks?|"
    r"questions?|examples?|ways?|recommendations?|takeaways?|steps?|"
    r"considerations?|issues?|themes?)"
)

_REQUEST_PATTERNS = (
    re.compile(
        rf"\btop\s+(?P<count>{_NUMBER_TOKEN})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:give|list|name|provide|show)\s+(?:me\s+)?(?:the\s+)?"
        rf"(?P<count>{_NUMBER_TOKEN})\s+{_COUNT_NOUN}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\btell\s+me\s+(?:the\s+)?(?P<count>{_NUMBER_TOKEN})\s+"
        rf"{_COUNT_NOUN}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<count>{_NUMBER_TOKEN})\s+{_COUNT_NOUN}\b",
        re.IGNORECASE,
    ),
)

_LIST_ITEM_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\d{1,2}[.)]|[-*•])\s+\S",
    re.MULTILINE,
)

_SUPPORTED_SHORTFALL_RE = re.compile(
    r"\b(?:only|just)\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:grounded|supported|relevant|distinct|clear)?\s*"
    r"(?:items?|things?|points?|topics?|priorities?|examples?|reasons?)\b",
    re.IGNORECASE,
)


def _parse_count_token(token: str) -> int | None:
    normalized = token.strip().lower()

    if normalized.isdigit():
        value = int(normalized)
        if 1 <= value <= 10:
            return value
        return None

    return _NUMBER_WORDS.get(normalized)


def extract_requested_count(user_prompt: str) -> int | None:
    """Return an explicit small requested item count, when present."""
    for pattern in _REQUEST_PATTERNS:
        match = pattern.search(user_prompt or "")
        if not match:
            continue

        count = _parse_count_token(
            match.group("count")
        )

        if count is not None:
            return count

    return None


def count_structured_items(response: str) -> int:
    """Count top-level-looking numbered/bulleted response items."""
    return len(
        _LIST_ITEM_RE.findall(response or "")
    )


def has_explicit_supported_shortfall(response: str) -> bool:
    """Detect an explicit statement that fewer grounded items exist."""
    return bool(
        _SUPPORTED_SHORTFALL_RE.search(response or "")
    )


def needs_count_retry(
    user_prompt: str,
    response: str,
) -> tuple[bool, int | None, int]:
    """
    Decide whether one compliance retry is warranted.

    The check is intentionally narrow: only explicit small-count requests are
    considered. A response that explicitly says fewer grounded items are
    supported is accepted rather than forcing hallucinated filler.
    """
    requested_count = extract_requested_count(
        user_prompt
    )

    if requested_count is None or requested_count <= 1:
        return False, requested_count, 0

    observed_count = count_structured_items(
        response
    )

    if observed_count == requested_count:
        return False, requested_count, observed_count

    if has_explicit_supported_shortfall(response):
        return False, requested_count, observed_count

    return True, requested_count, observed_count


def build_count_retry_prompt(
    base_prompt: str,
    user_prompt: str,
    requested_count: int,
) -> str:
    """Append a single strict count-correction instruction to an LLM prompt."""
    return (
        f"{base_prompt}\n\n"
        "COUNT COMPLIANCE CORRECTION\n\n"
        "Your previous answer did not clearly satisfy the user's requested "
        f"count of {requested_count} items.\n"
        f"Return exactly {requested_count} distinct items in a numbered list "
        f"from 1 through {requested_count}, when that many items are grounded "
        "in the supplied meeting context.\n"
        "If fewer than the requested number are genuinely supported, do not "
        "invent filler. Explicitly state how many supported items are available "
        "and return only those supported items.\n"
        "Do not add an introduction, conclusion, extra section, or offer to do "
        "more.\n\n"
        "The user's current request is:\n\n"
        f"{user_prompt}\n\n"
        "Answer that request directly and obey the requested count."
    )
