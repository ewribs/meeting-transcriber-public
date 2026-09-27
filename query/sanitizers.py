import re


def strip_action_sections(text: str) -> str:
    lines = text.splitlines()
    kept = []
    skipping = False

    action_headings = (
        "next steps",
        "next attention",
        "action items",
        "actions",
        "follow-ups",
        "follow ups",
        "suggested discussion",
        "open questions",
    )

    for line in lines:
        stripped = line.strip()

        normalized = (
            stripped
            .replace("*", "")
            .replace("_", "")
            .lower()
        )

        if (
            "no " in normalized
            and any(
                phrase in normalized
                for phrase in (
                    "commitment",
                    "follow-up",
                    "follow up",
                    "grounded action",
                )
            )
        ):
            continue

        if any(
            normalized.startswith(
                f"- {phrase}:"
            )
            or normalized.startswith(
                f"{phrase}:"
            )
            for phrase in action_headings
        ):
            continue

        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            heading = (
                heading
                .strip("*")
                .strip()
                .lower()
            )

            if any(
                phrase in heading
                for phrase in action_headings
            ):
                skipping = True
                continue

            skipping = False

        if not skipping:
            kept.append(line)

    cleaned = "\n".join(
        kept
    ).strip()

    cleaned = re.sub(
        r"\bnext week\s*"
        r"\(\d{4}-\d{2}-\d{2}\)",
        "next week",
        cleaned,
        flags=re.IGNORECASE,
    )

    return cleaned


def strip_question_only_blocks(
    text: str,
) -> str:
    lines = text.splitlines()
    kept = []

    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if (
            stripped.startswith("-")
            and stripped.endswith("?")
        ):
            index += 1
            continue

        if stripped.startswith("#"):
            block = [line]
            lookahead = index + 1

            while (
                lookahead < len(lines)
                and not lines[
                    lookahead
                ].strip().startswith("#")
                and lines[
                    lookahead
                ].strip() != "---"
            ):
                block.append(
                    lines[lookahead]
                )
                lookahead += 1

            content_lines = [
                item.strip()
                for item in block[1:]
                if item.strip()
            ]

            if (
                content_lines
                and all(
                    item.startswith("-")
                    and item.endswith("?")
                    for item in content_lines
                )
            ):
                index = lookahead
                continue

        kept.append(line)
        index += 1

    return "\n".join(kept).strip()


def clean_markdown_artifacts(
    text: str,
) -> str:
    lines = []

    for line in text.splitlines():
        stripped = line.strip().lower()

        if stripped in (
            "```",
            "```markdown",
        ):
            continue

        lines.append(line)

    while lines:
        if not lines[-1].strip():
            lines.pop()
            continue

        if lines[-1].strip().startswith(
            "#"
        ):
            lines.pop()
            continue

        break

    return "\n".join(lines).strip()
