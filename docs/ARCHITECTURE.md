# Architecture

## Guiding rule

**Swift owns the native application experience. Python remains the backend/source of truth.**

Do not reimplement meeting-processing, query, persistence, or publishing semantics independently in Swift unless the architecture is intentionally changed across both layers.

## Native application

The supported app lives in:

```text
swift/Meeting Transcriber/
```

The main workspaces are:

- Transcribe
- Meetings
- Search

The **Meetings** workspace is the main working area. It has a sidebar (All Meetings, Recent, Unpublished, Not in a Folder, Folders, Dynamic and Fixed sessions), a meeting list, and a detail area with **Meeting**, **Ask** and (for a selected session) **Changes** views. It is split across several `MeetingsView+*.swift` files by concern: rail/sidebar, ordering, organizing (folders and Add-to menus), folder-to-session, 1v1 sessions, list/grouping, and context/Ask. Sessions are managed entirely inside Meetings; the old standalone Sessions workspace has been removed.

Small view preferences (Recent window, sort, density, grouping, sidebar rows) are stored with `@AppStorage`, not in the Python settings, because they only affect presentation. Storage, local-AI and retention settings go through the backend (`preferences` / `save-preferences`).

### Startup sequence

When the app starts it runs, in order and best effort: audio retention, a state backup, and recovery of any unfinished recording. When the Meetings workspace loads or the set of meetings changes (new, published, deleted), every Dynamic session is refreshed.

`BackendService.swift` launches the Python bridge at `backend_bridge.py` using the repository's `.venv/bin/python`. `BackendService` and `TranscriptionService` share the same repository resolver: `MEETING_TRANSCRIBER_PROJECT_DIR`, then Application Support `install.json`, with `~/Projects/meeting-transcriber` retained only as a compatibility fallback.

## Python bridge

`backend_bridge.py` is the native application's JSON command boundary. It exposes lightweight commands for:

- meetings and meeting detail;
- publish/delete/unpublish workflows;
- sessions and saved conversation history, including the dynamic-session editor, criteria preview, `refresh-session` and `refresh-all-sessions`;
- folders (create, rename, delete, reorder) and the manual order of sessions in the sidebar;
- meeting-context queries and synthesis;
- session changes (`session-changes`);
- global search, with an optional folder or session scope;
- local state backups (`backup-state`) and startup retention;
- audio-contract validation/finalization;
- prompt favorites;
- preferences and performance-profile preview/save.

The bridge should reuse existing Python services rather than duplicating business logic.

## Meeting processing pipeline

A typical transcription run is coordinated by `transcribe.py` / `pipeline.py` and related services.

```text
M4A source
  |
  +-- extract Remote c0 / Mic c4 WAVs
  +-- Whisper (~5 minute chunks)
  +-- merge speaker VTTs
  +-- cleaned transcript
  +-- local AI narrative summary
  +-- grounded structured extraction
  +-- meeting_memory.json
  +-- deterministic final summary composition
  +-- metadata / HTML / OneNote artifacts
```

The meeting-memory pipeline is intentionally precision-sensitive. Decisions, commitments/follow-ups, and open questions are grounded/reconciled before final structured composition. Avoid adding independent post-processing layers without integration tests that exercise the production path.

## Local AI execution

`performance_profile.py` defines:

- Auto
- Conservative
- Balanced
- High Performance

Auto chooses a tier primarily from detected unified memory. A context-size override changes the effective context window while preserving the selected performance tier.

`query/execution.py` and related query modules decide whether a workload can run directly or should be chunked.

Local inference is routed through `llm_backend.py`. The backend preference supports Auto, Ollama, and MLX. Auto selects the MLX 30B path on Apple Silicon Macs with at least 36 GB of detected unified memory when the MLX runtime is available; otherwise it falls back to Ollama. Manual Ollama and MLX overrides remain available. MLX model weights are loaded lazily, and backend selection does not alter recording, transcription, grounding, or publishing semantics.

## Query/session architecture

The `query/` package contains multi-meeting selection, pruning, execution, synthesis, change analysis, session context, rendering, and chat helpers.

Saved sessions persist meeting selection plus conversation history, as JSON files in `query_sessions/` under the archive. There are two kinds:

- **Fixed** sessions store an explicit list of meeting runs and no criteria.
- **Dynamic** sessions also store `selection_criteria`: a set of rules (person, people, title/topic include and exclude, and a date window) and a `match` mode, `all` (default) or `any`. `meeting_selector.py` evaluates the rules and `session_rules.py` defines the rule keys. A dynamic session's `meeting_runs` is a saved snapshot of the last evaluation; it is re-evaluated by `refresh-session` / `refresh-all-sessions`, which the app calls on startup and when the meeting set changes.

Session change analysis (`session-changes`) is cached separately from membership, so refreshing membership does not discard or overwrite a comparison.

The Swift app loads and continues sessions through backend-bridge commands; Python remains authoritative for persistence.

## Organizing data

Two small files next to the meeting archive hold the user's organization of meetings. Both are written atomically and are never touched by meeting rebuilds.

| File | Purpose |
| --- | --- |
| `meeting_folders.json` | Folders and the meeting runs in each, in display order. A meeting can be in several folders. |
| `sidebar_order.json` | Manual order of Dynamic and Fixed sessions: `{"dynamic": [...], "fixed": [...]}`. Sessions missing from a list appear after the listed ones. |

Whether the sidebar uses A–Z or the manual order is a Swift display preference; the backend only stores the manual order.

## Recovery and backups

- **Recording recovery.** While recording, the Swift app writes raw Float32 audio to disk with a small sidecar JSON in `~/Library/Application Support/Meeting Transcriber/PendingRecordings/`. On launch it finalizes any leftover capture through `finalize-audio-recording`, then queues the result. A failed finalization keeps the raw file.
- **State backups.** `state_backup.py` copies `meeting_folders.json`, `sidebar_order.json` and `query_sessions/*.json` into `local_backups/` inside the project (Git-ignored). A snapshot is written only when something changed, and the newest 20 are kept. Backing up never modifies the originals. Use `tools/mt backup`, `--list` and `--restore NAME`.

## Installation metadata

The native app needs to locate the Python checkout before it can call the backend.
Setup writes a small non-secret file at:

```text
~/Library/Application Support/Meeting Transcriber/install.json
```

It contains the configured `project_dir`. Application preferences remain in the
separate `settings.json` file in the same Application Support directory. This
keeps install location separate from meeting/runtime settings and lets the public
installer support arbitrary checkout locations.

## Storage model

Typical local run:

```text
output/<run>/
├── audio/
├── transcript/
├── meeting_transcript.md
├── meeting_transcript_cleaned.md
├── meeting_summary.md
├── meeting_metadata.json
├── meeting_memory.json
└── processing_runtime.json
```

Published runs are copied to the configured archive. The source M4A is archived separately under the published meeting's `source/` folder and verified before retention can remove a local source copy.

See [File Lifecycle & Retention](FILE_LIFECYCLE.md).

## Audio contract

The native recorder and Python pipeline share one channel contract:

- Input device name: `Transcribe`
- minimum input channels: 5
- Remote: channel index 0 (`c0`)
- Mic: channel index 4 (`c4`)

The native recorder captures interleaved Float32 PCM and finalizes it with ffmpeg to a five-channel M4A. `audio_contract.py` validates the resulting file using the same channel extraction rules used by transcription.

## Repository boundaries

- Root Python modules: supported backend/service code.
- `query/`: supported query engine.
- `tests/`: automated regression tests only.
- `tools/`: manual maintenance/backfill/diagnostic/CLI helpers.
- `swift/`: supported native app.
- `legacy/qt/`: retired Qt front end retained for reference only.
- `docs/internal/`: historical planning/migration notes, not authoritative product docs.

## Private runtime identity

Self-identification is runtime data, not application source. `identity_config.py` loads `identity.local.json`, which is ignored by Git. `config.py` exposes the resulting `SELF_NAME`, `SELF_REFERENCE_NAMES`, and `SELF_SPEAKER_LABEL` values to existing attribution logic in `ai.py`.

This boundary is intentional: public code contains only generic defaults and an example schema, while a user's real identity remains local. The identity values participate in participant filtering and owner/follow-up normalization, so they should be externalized rather than removed or globally replaced.
## Private runtime context

Organization-specific runtime context must not be hard-coded in committed source.
The application supports public-safe defaults/examples plus Git-ignored local
overrides. User identity is loaded from `identity.local.json`; organization-specific
topic normalization is loaded from `business_context.local.json`. Schema or behavior
changes to these private-context features must update the public example, loader,
tests, and documentation in the same change.
