# User Guide

Meeting Transcriber is organized into four workspaces: **Transcribe**, **Meetings**, **Sessions**, and **Search**.

## Transcribe

### Record a meeting

1. Configure a Recordings folder in Preferences.
2. Confirm the input monitor sees the `Transcribe` device and reports the expected five-channel format.
3. Enter a meeting name if desired.
4. Start recording.
5. Stop recording when finished.
6. The app finalizes the raw capture to a compatible M4A and adds it to the transcription queue.

If finalization fails, the app keeps the recoverable raw capture rather than silently discarding it.

### Add an existing recording

Use **Add Existing Recording…** in Transcribe. The configured Recordings folder is the default browser location, but you can choose a recording elsewhere.

Queued recordings are processed sequentially.

### Processing stages

A normal run performs local audio extraction, Whisper transcription, transcript cleanup, local AI summarization, structured meeting-memory extraction, metadata generation, HTML/OneNote artifact creation, and runtime metadata capture.

The current Whisper strategy uses approximately five-minute chunks. Summary/query execution may run directly or chunked depending on the selected performance profile and workload size.

## Meetings

The Meetings workspace includes both unpublished local runs and published/archived meetings.

A meeting can expose:

- Summary.
- Cleaned transcript.
- Structured Topics.
- Decisions.
- Action items / commitments / follow-ups when grounded in the meeting.
- Open questions.
- Processing metadata.

The detail view supports normal text selection/copy.

### Publish & Archive

Publishing copies the completed run to the configured archive, verifies the source M4A copy, updates archive indexes/exports, removes temporary WAVs, and applies configured retention rules.

See [File Lifecycle & Retention](FILE_LIFECYCLE.md) for the complete safety model.

### Delete / Unpublish

The app performs a plan/validation step before destructive meeting operations. Saved-session references and archive/local state are reconciled rather than blindly deleting files.

## Sessions

Sessions let you work with a persistent set of meetings instead of asking one-off questions.

A saved session can include:

- Fixed selected meetings, or dynamic selection criteria.
- Person/title/topic/date criteria where supported.
- Persistent conversation history.
- Cached changes/delta analysis.

Opening a saved session reloads its persisted conversation history. New user/assistant turns are appended through the Python backend, so the same session can be resumed later.

### Asking questions

Use the Conversation view to ask questions across the session's meeting context. The backend chooses direct or chunked execution according to the effective performance profile and available context.

### Changes

For supported saved sessions, the Changes view compares recent meeting evidence and preserves grounded status/action/decision semantics rather than inferring changes from absence alone.

## Search

Search performs a global search across indexed meeting and session content. Results can navigate directly to the relevant Meeting or Session workspace.

## Preferences

### Storage

Configure:

- Output folder — local processing runs and unpublished meeting artifacts.
- Archive folder — published meeting archive/NAS root.
- Recordings folder — default location for native recordings and Add Recordings browsing.

### Local AI model

The model list is discovered from local Ollama. Use **Refresh Models** after installing or removing Ollama models.

### AI backend

Preferences offers **Auto (Recommended)**, **Ollama**, and **MLX**. Auto uses MLX with the configured 30B model on supported Apple Silicon Macs with at least 36 GB of unified memory when `mlx-lm` is available; otherwise it uses the configured Ollama model. The Preferences window shows the effective backend and model before you save. Manual Ollama and MLX selections override Auto.

The Ollama model remains configured as the portable fallback. MLX model weights are loaded only when MLX is actually used; the first use may need to obtain the configured model if it is not already present in the local Hugging Face cache.

### Performance profile

Available profiles:

- **Auto** — recommended. Resolves from detected Mac hardware/unified memory.
- **Conservative** — smaller direct contexts and earlier chunking.
- **Balanced** — moderate direct context and chunk sizes.
- **High Performance** — largest direct contexts before chunking, intended for Macs with ample unified-memory headroom.

Preferences shows the detected hardware, effective profile, effective context, and direct budget.

### Context override

Leave **Context override** at **Profile default** for normal use. An override changes the Ollama context window but does not change the selected performance tier. It is intended for deliberate testing/tuning rather than everyday operation.

### Audio retention

Local source M4A and archived source M4A retention are configured independently. Retention is conservative: when archive verification is ambiguous, audio is kept rather than deleted.

An archived retention value of `0` means **Forever**.

## Recovery behavior

Meeting Transcriber intentionally separates transcription completion from publishing. If publishing fails after a meeting was processed successfully, the completed local run remains available and can be published again without retranscribing.

The backend also supports recovery/resume paths for completed transcripts/summaries when downstream artifact creation failed.

## Data and privacy

Meeting processing is designed to stay local:

- Whisper runs locally.
- Ollama runs locally.
- Meeting/session data is stored in configured local/archive locations.

Normal operation does not require sending transcript content to a hosted model service.
