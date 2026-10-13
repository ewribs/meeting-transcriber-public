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
- Sessions
- Search

`BackendService.swift` launches the Python bridge at `backend_bridge.py` using the repository's `.venv/bin/python`. `BackendService` and `TranscriptionService` share the same repository resolver: `MEETING_TRANSCRIBER_PROJECT_DIR`, then Application Support `install.json`, with `~/Projects/meeting-transcriber` retained only as a compatibility fallback.

## Python bridge

`backend_bridge.py` is the native application's JSON command boundary. It exposes lightweight commands for:

- meetings and meeting detail;
- publish/delete/unpublish workflows;
- sessions and saved conversation history;
- meeting-context queries and synthesis;
- global search;
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

Saved sessions persist meeting selection/criteria plus conversation history. The Swift app loads and continues those sessions through backend-bridge commands; Python remains authoritative for persistence.

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
