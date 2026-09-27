from __future__ import annotations

from pathlib import Path
from typing import Callable


class UnsavedSessionError(ValueError):
    pass


def _default_save_session():
    from query.sessions import save_chat_session

    return save_chat_session


def append_query_exchange(
    session: dict,
    meeting_dirs: list[Path],
    *,
    user_prompt: str | None,
    assistant_response: str,
    save_session_func: Callable[..., Path] | None = None,
) -> list[dict]:
    """Append one completed query exchange and persist a saved session.

    The supplied session dictionary is updated in place so existing UI/backend
    consumers continue to share the same conversation-history object.
    """
    session_name = session.get("session_name")
    if not session_name:
        raise UnsavedSessionError(
            "Conversation history can only be persisted for a saved session."
        )

    history = session.setdefault("conversation_history", [])

    normalized_prompt = (user_prompt or "").strip()
    if normalized_prompt:
        history.append(
            {
                "role": "user",
                "content": normalized_prompt,
            }
        )

    history.append(
        {
            "role": "assistant",
            "content": assistant_response,
        }
    )

    save_session = save_session_func or _default_save_session()
    save_session(
        session_name,
        meeting_dirs,
        history,
        session.get("selection_criteria"),
    )

    return history
