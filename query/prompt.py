import json


def build_query_prompt(
    resolved_user_prompt: str,
    today: str,
    merged_memory: dict,
    conversation_history: list[dict] | None = None,
) -> str:
    llm_memory = dict(
        merged_memory
    )

    llm_memory.pop(
        "commitments",
        None,
    )

    llm_memory.pop(
        "topic_follow_ups",
        None,
    )

    llm_memory.pop(
        "unassigned_follow_ups",
        None,
    )

    llm_memory.pop(
        "topic_open_questions",
        None,
    )

    llm_memory.pop(
        "unassigned_open_questions",
        None,
    )

    history_text = json.dumps(
        conversation_history or [],
        indent=2,
    )

    prompt = f"""
You are analyzing chronological machine-readable memories
from multiple business meetings.

Previous conversation turns:

{history_text}

User request:

{resolved_user_prompt}

Current date for relative-date resolution only:

{today}

Rules:

USER REQUEST SCOPE
- The user's current request controls the scope, length, topic, and format of the answer.
- Answer only what the user asked for.
- If the user asks about one topic, discuss only that topic unless another topic is strictly necessary to answer.
- If the user asks for one sentence, return exactly one sentence.
- If the user asks for a specific number of items, return exactly that number when that many grounded items are supported by the meeting memory.
- If fewer grounded items are genuinely supported, explicitly say how many supported items are available and return only those items; never invent filler to reach the requested count.
- If the user asks for a brief or concise answer, do not provide a comprehensive summary.
- Do not summarize the entire meeting memory unless the user explicitly asks for a comprehensive summary.
- Do not add tables, overviews, reports, highlights, risks, next steps, or additional sections unless requested.
- Do not offer additional work at the end of the response.

SOURCE OF TRUTH
- Use only the supplied merged meeting memory.
- Meeting memory is the source of truth for meeting facts.
- Previous conversation turns are supplied only to resolve conversational references such as "those", "that", "the second one", or "what you just said".
- Never treat something from prior conversation as a meeting fact unless it is supported by the meeting memory.

DATE HANDLING
- Resolve relative dates in the user's request, such as "today", "tomorrow", "next Monday", and "next week", using the supplied current date.
- Never invent a different current date.
- The supplied current date is reference context only. It is not the date of the user's requested meeting.
- If the user refers to "next Monday", use the supplied Next Monday date exactly. Do not calculate it yourself.
- Never assign a date to a future meeting unless the user's request explicitly supplies or resolves to that date.
- Do not resolve relative dates found inside meeting-memory content using today's date.
- Preserve phrases such as "next week" inside meeting-memory content unless the user explicitly asks for date interpretation.

MEETING CONTEXT
- anchor_meeting is the primary meeting context for this request.
- anchor_topics contains topics from the primary meeting and should receive the strongest weight.
- supporting_topics contains topics from later or related meetings and should provide supporting context, not replace the anchor meeting.
- recurring_topics contains only topics confirmed to recur across multiple meetings.
- Never call a topic recurring unless it appears in recurring_topics.
- Do not resurrect topics that appear only in topic_history.
- If a topic is closed, treat it as historical context only unless a later meeting explicitly reopens it.
- Do not let a later supporting meeting erase or demote unresolved topics from the anchor meeting.

TOPIC PRIORITY
- Prioritize topics in this order:
  1. anchor_topics
  2. recurring topics that remain open or ongoing
  3. supporting_topics when they materially affect the user's request
- When the user asks which topics are most important, most relevant, highest priority, or current, prefer topics from the anchor meeting first.
- Use recurring topics only when they materially outweigh an anchor topic.
- Use latest supporting topics to add context, not to displace anchor topics unless clearly more important.
- Do not elevate an older recurring topic solely because it is recurring.
- When preparing for a future meeting, focus on the latest actionable state while preserving unresolved items from the anchor meeting.

OPEN QUESTIONS
- Do not output open questions or assign questions to topics.
- Do not invent open questions from topic summaries, risks, concerns, or unresolved issues.
- Grounded open questions are rendered separately by the application.
- topic_open_questions contains open questions safely associated with a specific topic.
- unassigned_open_questions contains questions with no safe topic association.
- Never attach an unassigned open question to an individual topic.
- Do not state whether open questions exist or do not exist.

ACTIONS AND COMMITMENTS
- Do not output commitments, follow-ups, next steps, action items, action required, or suggested discussion points.
- Grounded actions are rendered separately by the application.
- If the user's request explicitly asks for actions, commitments, follow-ups, next steps, or what they need to do, do not answer that portion directly.
- Instead, identify and summarize only the relevant topics, current status, and context that make the grounded actions relevant.
- Do not phrase topic summaries as instructions or recommendations.
- Do not begin topic-detail bullets with imperative verbs such as "update", "clarify", "review", "evaluate", "determine", "assess", "develop", "establish", "roll out", "communicate", "integrate", or "improve".
- A confirmed commitment must come only from the commitments list.
- Do not label a status, topic, follow-up, risk, concern, open question, or desired outcome as a commitment.
- Do not treat a historical follow-up as current just because it exists in meeting history.
- Never assign a commitment or follow-up to a topic unless the action is clearly about that topic.
- If no topic-specific action exists, omit the action instead of inferring one.
- Do not invent "Next Steps", "Action Required", "Follow-Up", or similar action labels from a topic summary alone.
- Only treat something as a next step, follow-up, or commitment if it is explicitly present in commitments or follow_ups.
- Never convert an unresolved topic, open question, risk, concern, or desired outcome into an action.
- topic_follow_ups contains follow-ups safely associated with a specific topic.
- unassigned_follow_ups contains general follow-ups that must not be attached to an individual topic.
- Do not state whether commitments, follow-ups, or actions exist or do not exist.

OUTPUT
- Your job is to summarize, synthesize, and prioritize topics, status, and context only.
- Follow the user's requested output format closely.
- Use concise Markdown.

Merged chronological meeting memory:

{json.dumps(llm_memory, indent=2)}

FINAL RESPONSE INSTRUCTION

The user's current request is:

{resolved_user_prompt}

Answer that request directly.

The current user request overrides any tendency to provide a
general meeting summary.

Do not summarize unrelated topics.

Do not provide additional sections, tables, recommendations,
next steps, or offers to do more unless the user requested them.

If the user requested one sentence, output exactly one sentence
and nothing else.

""".strip()

    return prompt
