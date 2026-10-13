from __future__ import annotations

from session_browser import format_session_criteria


def format_elapsed(elapsed_ms: int) -> str:
    total_seconds = max(0, int(elapsed_ms) // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def format_query_ready_status(profile_name: str) -> str:
    return f"Qwen · {profile_name} · Ready"


def format_query_working_status(profile_name: str) -> str:
    return f"Qwen · {profile_name} · Working…"


def format_query_error_status(profile_name: str) -> str:
    return f"Qwen · {profile_name} · Error"


def format_query_finished_status(metadata: dict, fallback_profile: str) -> str:
    profile = metadata.get("profile", fallback_profile)
    resolved_profile = metadata.get("resolved_profile") or profile
    profile_label = (
        f"{profile}→{resolved_profile}"
        if profile == "Auto" and resolved_profile != profile
        else str(resolved_profile)
    )
    mode = metadata.get("mode", "direct")
    inference_calls = int(metadata.get("inference_calls", 1))

    if mode == "chunked":
        return f"Qwen · {profile_label} · Chunked · {inference_calls} passes"

    if inference_calls > 1:
        return f"Qwen · {profile_label} · Direct · {inference_calls} passes"

    return f"Qwen · {profile_label} · Direct"


def render_conversation_markdown(history: list[dict] | None) -> str:
    parts: list[str] = []

    for item in history or []:
        role = item.get("role", "")
        content = item.get("content", "")

        if not content:
            continue

        if role == "user":
            heading = "### You"
        elif role == "assistant":
            heading = "### Assistant"
        else:
            continue

        parts.extend(
            [
                heading,
                "",
                content,
                "",
                "---",
                "",
            ]
        )

    return "\n".join(parts)


def format_session_prep(
    prep: dict,
    heading: str,
    selection_criteria: dict | None = None,
) -> str:
    lines = [heading, ""]

    criteria_lines = (
        format_session_criteria(selection_criteria)
        if selection_criteria
        else []
    )

    if criteria_lines:
        lines.extend(criteria_lines)
        lines.append("")

    lines.extend(
        [
            f"Meetings in context: {prep['meeting_count']}",
            f"Anchor: {prep['anchor_label']}",
        ]
    )

    if prep["supporting_labels"]:
        lines.extend(["", "SUPPORTING MEETINGS", "-------------------"])
        for label in prep["supporting_labels"]:
            lines.append(f"• {label}")

    lines.extend(["", "PRIORITIES", "----------"])

    for priority in prep["priorities"]:
        markers = []
        if priority["anchor"]:
            markers.append("Anchor")
        if priority["recurring"]:
            markers.append("Recurring")
        if priority["supporting"]:
            markers.append("Supporting")

        marker_text = f" [{', '.join(markers)}]" if markers else ""
        lines.append(f"• {priority['topic']}{marker_text}")

        if priority["summary"]:
            lines.append(f"  {priority['summary']}")
        if priority["status"]:
            lines.append(f"  Status: {priority['status']}")
        lines.append("")

    topic_questions = prep["questions"]["topic"]
    general_questions = prep["questions"]["general"]
    lines.extend(["OPEN QUESTIONS", "--------------"])

    if not topic_questions and not general_questions:
        lines.append("No grounded open questions.")

    for group in topic_questions:
        lines.append(f"{group['topic']}:")
        for question in group["questions"]:
            lines.append(f"• {question}")
        lines.append("")

    if general_questions:
        lines.append("General:")
        for question in general_questions:
            lines.append(f"• {question}")
        lines.append("")

    actions = prep["actions"]
    lines.extend(["ACTIONS / FOLLOW-UPS", "--------------------"])

    has_actions = any(
        (
            actions["commitments"],
            actions["topic_follow_ups"],
            actions["general_follow_ups"],
        )
    )

    if not has_actions:
        lines.append("No grounded actions or follow-ups.")

    for commitment in actions["commitments"]:
        owner = commitment.get("owner") or "Unassigned"
        lines.append(f"• {owner}: {commitment['action']}")

    for group in actions["topic_follow_ups"]:
        lines.append(f"{group['topic']}:")
        for follow_up in group["follow_ups"]:
            lines.append(f"• {follow_up}")
        lines.append("")

    if actions["general_follow_ups"]:
        lines.append("General:")
        for follow_up in actions["general_follow_ups"]:
            lines.append(f"• {follow_up}")

    return "\n".join(lines)


def format_auto_execution_tooltip(metadata: dict) -> str:
    estimated_tokens = int(metadata.get("estimated_prompt_tokens", 0))
    direct_budget = int(metadata.get("direct_token_budget", 0))
    context_size = int(metadata.get("context_size_tokens", 0))
    context_reserve = int(metadata.get("context_reserve_tokens", 0))
    model_factor = float(metadata.get("model_budget_factor", 1.0))
    hardware_factor = float(metadata.get("hardware_budget_factor", 1.0))
    calibration_factor = float(metadata.get("calibration_factor", 1.0))
    sample_count = int(metadata.get("calibration_sample_count", 0))
    median_elapsed = metadata.get("calibration_median_elapsed_seconds")
    calibration_reason = (
        metadata.get("calibration_reason")
        or "No local calibration applied."
    )

    if context_size > 0:
        context_text = f"{context_size:,} tokens ({context_reserve:,} reserved)"
    else:
        context_text = "Model default"

    if sample_count < 5:
        calibration_status = (
            f"{sample_count}/5 comparable samples before calibration can influence Auto"
        )
    else:
        calibration_status = f"{sample_count} comparable samples"

    requested_profile = str(metadata.get("profile") or "Auto")
    resolved_profile = str(
        metadata.get("resolved_profile")
        or requested_profile
    )

    lines = [
        "Auto execution details",
        f"Performance profile: {requested_profile} → {resolved_profile}"
        if requested_profile == "Auto"
        else f"Performance profile: {resolved_profile}",
        f"Mode: {metadata.get('mode', 'direct').title()}",
        f"Estimated prompt: {estimated_tokens:,} tokens",
        f"Effective direct budget: {direct_budget:,} tokens",
        f"Configured context: {context_text}",
        f"Model factor: {model_factor:.2f} · Hardware factor: {hardware_factor:.2f}",
        f"Local calibration factor: {calibration_factor:.2f}",
        f"Calibration history: {calibration_status}",
    ]

    if median_elapsed is not None:
        lines.append(f"Comparable median: {float(median_elapsed):.1f}s")

    profile_reason = metadata.get("profile_reason")
    if profile_reason:
        lines.append(f"Profile reason: {profile_reason}")

    lines.append(f"Calibration reason: {calibration_reason}")

    if int(metadata.get("count_retry_count", 0)) > 0:
        lines.append("Count compliance retry: yes")

    return "\n".join(lines)
