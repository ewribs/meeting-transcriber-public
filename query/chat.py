from config import (
    LLM_CONTEXT_SIZE,
    LLM_MODEL,
)
from ai import ask_llm
from hardware_profile import detect_hardware_profile
from execution_calibration import (
    get_execution_calibration,
)
from query.context import build_meeting_context
from query.count_compliance import (
    build_count_retry_prompt,
    needs_count_retry,
)
from query.dates import resolve_query_dates
from query.execution import (
    build_chunk_evidence_prompt,
    build_chunk_synthesis_prompt,
    build_execution_metadata,
    choose_execution_plan,
    chunk_meeting_sources,
    get_execution_profile,
)
from query.meeting_selection import (
    select_query_meetings,
)
from query.prompt import build_query_prompt
from query.pruning import prepare_query_memory
from query.sanitizers import (
    clean_markdown_artifacts,
    strip_action_sections,
    strip_question_only_blocks,
)

from query.rendering import (
    format_grounded_sections,
    render_grounded_sections,
)


def _sanitize_model_result(result: str) -> str:
    result = strip_action_sections(
        result
    )

    result = strip_question_only_blocks(
        result
    )

    return clean_markdown_artifacts(
        result
    )


def run_query(
    user_prompt: str,
    merged_memory: dict,
    conversation_history: list[dict] | None = None,
    include_grounded: bool = False,
    print_output: bool = True,
    meeting_memories: list[tuple[str, dict]] | None = None,
    selected_meetings: list[dict] | None = None,
    topic_filter: str | None = None,
    return_execution_metadata: bool = False,
    execution_profile: str = "Auto",
) -> str | tuple[str, dict]:
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

    llm_user_prompt = user_prompt

    if any(
        term in user_prompt.lower()
        for term in action_terms
    ):
        llm_user_prompt = (
            "Identify and summarize only the current "
            "topics, status, and context most relevant "
            "to the user's request. "
            "Do not provide actions, commitments, "
            "follow-ups, recommendations, next steps, "
            "questions, or instructions."
        )

    (
        resolved_user_prompt,
        today,
    ) = resolve_query_dates(
        llm_user_prompt
    )

    model_base_memory = merged_memory

    if (
        meeting_memories
        and selected_meetings
    ):
        (
            query_meeting_memories,
            query_selected_meetings,
        ) = select_query_meetings(
            user_prompt,
            meeting_memories,
            selected_meetings,
        )

        if (
            len(query_meeting_memories)
            < len(meeting_memories)
        ):
            query_context = build_meeting_context(
                query_meeting_memories,
                query_selected_meetings,
                topic_filter,
            )

            model_base_memory = query_context[
                "merged_memory"
            ]

    model_memory = prepare_query_memory(
        user_prompt,
        model_base_memory,
    )

    prompt = build_query_prompt(
        resolved_user_prompt,
        today,
        model_memory,
        conversation_history,
    )

    can_chunk = bool(
        query_meeting_memories
        if (
            meeting_memories
            and selected_meetings
        )
        else []
    )

    hardware_profile = (
        detect_hardware_profile()
    )

    calibration = get_execution_calibration(
        profile=execution_profile,
        model_name=LLM_MODEL,
        context_size_tokens=LLM_CONTEXT_SIZE,
        hardware_label=(
            hardware_profile.display_label
        ),
    )

    profile = get_execution_profile(
        execution_profile,
        context_size_tokens=LLM_CONTEXT_SIZE,
        model_name=LLM_MODEL,
        hardware_profile=hardware_profile,
        hardware_label=(
            hardware_profile.display_label
        ),
        hardware_performance_class=(
            hardware_profile.performance_class
        ),
        hardware_budget_factor=(
            hardware_profile.budget_factor
        ),
        calibration_factor=(
            calibration.factor
        ),
        calibration_sample_count=(
            calibration.sample_count
        ),
        calibration_median_elapsed_seconds=(
            calibration.median_elapsed_seconds
        ),
        calibration_reason=(
            calibration.reason
        ),
    )

    execution_plan = choose_execution_plan(
        prompt,
        can_chunk=can_chunk,
        direct_token_budget=(
            profile.direct_token_budget
        ),
    )

    if print_output:
        print()
        print(
            "Analyzing merged meeting memory... "
        )
        print(
            f"Execution mode: "
            f"{execution_plan.mode} "
            f"(~{execution_plan.estimated_prompt_tokens:,} "
            f"prompt tokens estimated)."
        )
        print()

    chunk_count = 0
    count_retry_count = 0
    final_generation_prompt = prompt

    if execution_plan.mode == "direct":
        result = ask_llm(
            prompt,
            timeout_seconds=getattr(profile, "llm_call_timeout_seconds", 120),
        )

    else:
        chunks = chunk_meeting_sources(
            query_meeting_memories,
            query_selected_meetings,
            chunk_source_token_budget=(
                profile.chunk_source_token_budget
            ),
        )

        chunk_count = len(chunks)

        chunk_findings = []

        for chunk_number, (
            chunk_memories,
            chunk_selected,
        ) in enumerate(
            chunks,
            start=1,
        ):
            chunk_context = build_meeting_context(
                chunk_memories,
                chunk_selected,
                topic_filter,
            )

            chunk_memory = prepare_query_memory(
                user_prompt,
                chunk_context["merged_memory"],
            )

            chunk_prompt = build_chunk_evidence_prompt(
                resolved_user_prompt,
                today,
                chunk_memory,
                chunk_number,
                len(chunks),
            )

            if print_output:
                print(
                    f"Analyzing chunk "
                    f"{chunk_number}/{len(chunks)}..."
                )

            chunk_findings.append(
                ask_llm(
                    chunk_prompt,
                    timeout_seconds=getattr(profile, "llm_call_timeout_seconds", 120),
                )
            )

        synthesis_prompt = (
            build_chunk_synthesis_prompt(
                resolved_user_prompt,
                today,
                chunk_findings,
                conversation_history,
            )
        )

        final_generation_prompt = synthesis_prompt

        result = ask_llm(
            synthesis_prompt,
            timeout_seconds=getattr(profile, "llm_call_timeout_seconds", 120),
        )

    result = _sanitize_model_result(
        result
    )

    count_retry_enabled = (
        llm_user_prompt == user_prompt
    )

    if count_retry_enabled:
        (
            should_retry_count,
            requested_count,
            observed_count,
        ) = needs_count_retry(
            user_prompt,
            result,
        )

        if (
            should_retry_count
            and requested_count is not None
        ):
            if print_output:
                print(
                    "Count compliance retry: "
                    f"requested {requested_count}, "
                    f"observed {observed_count}."
                )

            retry_prompt = build_count_retry_prompt(
                final_generation_prompt,
                resolved_user_prompt,
                requested_count,
            )

            result = _sanitize_model_result(
                ask_llm(
                    retry_prompt,
                    timeout_seconds=getattr(profile, "llm_call_timeout_seconds", 120),
                )
            )
            count_retry_count = 1

    if print_output:
        print(result)

        render_grounded_sections(
            user_prompt,
            merged_memory,
            conversation_history,
        )

    final_result = result

    if include_grounded:
        grounded_text = (
            format_grounded_sections(
                user_prompt,
                merged_memory,
                conversation_history,
            )
        )

        if grounded_text:
            final_result = (
                f"{result}\n\n"
                f"{grounded_text}"
            )

    if return_execution_metadata:
        execution_metadata = build_execution_metadata(
            execution_plan,
            chunk_count=chunk_count,
            profile_name=profile.name,
            resolved_profile_name=getattr(profile, "resolved_name", profile.name),
            profile_reason=getattr(profile, "profile_reason", ""),
            chunk_overlap_tokens=getattr(profile, "chunk_overlap_tokens", 0),
            context_size_tokens=(
                profile.context_size_tokens
            ),
            context_reserve_tokens=(
                profile.context_reserve_tokens
            ),
            model_name=profile.model_name,
            model_parameter_billions=(
                profile.model_parameter_billions
            ),
            model_budget_factor=(
                profile.model_budget_factor
            ),
            hardware_label=(
                profile.hardware_label
            ),
            hardware_performance_class=(
                profile.hardware_performance_class
            ),
            hardware_budget_factor=(
                profile.hardware_budget_factor
            ),
            calibration_factor=(
                profile.calibration_factor
            ),
            calibration_sample_count=(
                profile.calibration_sample_count
            ),
            calibration_median_elapsed_seconds=(
                profile.calibration_median_elapsed_seconds
            ),
            calibration_reason=(
                profile.calibration_reason
            ),
        )

        if count_retry_count:
            execution_metadata["inference_calls"] = (
                int(
                    execution_metadata.get(
                        "inference_calls",
                        1,
                    )
                )
                + count_retry_count
            )

        execution_metadata["count_retry_count"] = (
            count_retry_count
        )

        return (
            final_result,
            execution_metadata,
        )

    return final_result
