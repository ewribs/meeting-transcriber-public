# Swift Migration Readiness

## Current state

The Python application is close to the point where its PySide UI can be treated as a reference implementation and a native SwiftUI shell can be started without rewriting the backend.

Substantial non-Qt responsibilities have already been separated from `gui.py`:

- background workers (`gui_workers.py`)
- transcription queue state (`transcription_queue.py`)
- transcription queue orchestration (`queue_orchestrator.py`)
- Transcribe presentation/state formatting (`transcribe_ui.py`)
- Meetings browser/search/preview logic (`meeting_browser.py`)
- Meetings selection-state calculations (`meeting_selection_ui.py`)
- Sessions browser presentation (`session_browser.py`)
- session mutations (`session_actions.py`)
- dynamic-session criteria rules (`session_criteria_ui.py`)
- query presentation/status formatting (`query_presentation.py`)
- Preferences presentation/validation (`preferences_ui.py`)
- context construction for ad-hoc meetings and saved sessions (`context_service.py`)

The transcription, publishing/archive, query, session, retention, and meeting-index backends remain Python services independent of Swift.

## Remaining business logic in `gui.py`

### 1. Conversation-history persistence after a query

`_query_finished()` still appends the user/assistant turns to the active session and saves the updated session JSON. This should move to a small query/session persistence service before the Python UI is frozen.

### 2. Publish request preparation / validation

The Qt handlers still contain some publish preflight decisions such as:

- confirming the local run exists
- confirming the archive is mounted
- checking whether an archive folder already exists
- choosing the run to publish

The actual publishing operation is already behind `publish_workflow.py`; only request preparation/validation remains in the window. This can move to a small service shared by Transcribe and Meetings.

## Logic that can remain UI-specific

The following are appropriately owned by the UI layer and do not need to be extracted merely for Swift migration:

- `QThread` creation and signal wiring
- dialogs and confirmation prompts
- button enable/disable state
- timers and elapsed-time labels
- list selection and tab switching
- file pickers
- Qt checkbox painting/style workaround
- widget construction and layout

A SwiftUI application will replace these rather than reuse them.

## Recommended migration checkpoint

Complete the two remaining extractions above, run the existing Python regression suite plus one normal end-to-end transcription/publish/query cycle, then freeze PySide feature behavior.

At that point begin a SwiftUI shell with the Python implementation retained as the backend/reference implementation.

Initial SwiftUI migration order:

1. Transcribe
2. Meetings
3. Sessions
4. Preferences

Do not initially rewrite Whisper, Ollama/Qwen, publishing/archive, retention, or meeting/session storage in Swift. Establish a thin local boundary to the existing Python services first.
