# User Guide

Meeting Transcriber is organized into four workspaces: **Transcribe**, **Meetings**, **Sessions**, and **Search**. For a screen-by-screen tour and how-to recipes, see the [Swift App Guide](SWIFT_APP_GUIDE.md); this page describes behavior.

## Transcribe

### Record a meeting

1. Configure a Recordings folder in Preferences.
2. Confirm the input monitor sees the `Transcribe` device and reports the expected five-channel format.
3. Enter a meeting name if desired.
4. Start recording.
5. Stop recording when finished.
6. The app finalizes the raw capture to a compatible M4A and adds it to the transcription queue.

If finalization fails, the app keeps the recoverable raw capture rather than silently discarding it. If the app quits or crashes mid-recording, the unfinished capture is finalized and queued automatically the next time the app starts.

### Add an existing recording

Use **Add Existing Recording…** in Transcribe. The configured Recordings folder is the default browser location, but you can choose a recording elsewhere.

Queued recordings are processed sequentially.

### Processing stages

A normal run performs local audio extraction, Whisper transcription, transcript cleanup, local AI summarization, structured meeting-memory extraction, metadata generation, HTML/OneNote artifact creation, and runtime metadata capture.

The current Whisper strategy uses approximately five-minute chunks. Summary/query execution may run directly or chunked depending on the selected performance profile and workload size.

## Meetings

The Meetings workspace includes both unpublished local runs and published/archived meetings. A sidebar on the left filters the meeting list by **All Meetings**, **Recent**, **Unpublished**, **Not in a Folder**, your **Folders**, and your **Dynamic** and **Fixed** sessions. Folders and sessions can be sorted A–Z or dragged into a manual order. The list can be sorted, grouped by month or person, and shown at three densities.

### Folders

Folders are your own groupings; a meeting can be in several. A folder can be turned into a Fixed session with **Make Session from Folder…**.

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

### Ask and Changes

With meetings or a session selected, the **Ask** view answers questions across that context using the local model. When a session is selected, a **Changes** view compares its latest meetings.

### Delete / Unpublish

The app performs a plan/validation step before destructive meeting operations. Saved-session references and archive/local state are reconciled rather than blindly deleting files.

## Sessions

Sessions let you work with a persistent set of meetings instead of asking one-off questions. They appear in the Meetings sidebar (and in the Sessions workspace).

- **Fixed** sessions hold meetings you choose. They are created from a folder or by adding meetings with **Add to**.
- **Dynamic** sessions are defined by rules: person, any of several people, title contains / does not contain, topic contains / does not contain, and a date window. Choose **All rules** or **Any rule** to control how rules combine. The editor previews the matching meetings as you edit.

Dynamic sessions keep themselves current: their rules are re-run when the app opens and whenever a meeting is added, published, or deleted. **Refresh** forces it. **Make 1v1 Session With** creates a Dynamic session for one person's meetings with "1v1" in the title.

Opening a saved session reloads its persisted conversation history. New turns are appended through the Python backend, so the session can be resumed later.

### Asking questions

Use **Ask** to question the session's meeting context. The backend chooses direct or chunked execution according to the effective performance profile and available context.

### Changes

**What changed since last time?** compares the two most recent meetings in a session and preserves grounded status/action/decision semantics rather than inferring changes from absence alone.

## Search

Search performs a global search across indexed meeting and session content, optionally scoped to one folder or session. Results can navigate directly to the relevant Meeting or Session workspace.

## Preferences

Preferences has three tabs. **Storage** and **Local AI** are saved with the **Save** button; **Meetings** settings apply immediately.

- **Storage** — folders and recording retention.
- **Local AI** — backend, model, performance profile and context override.
- **Meetings** — "Recent" window, sort order, list density, sidebar rows and ordering, notices, confirmations, and prompt favorites.

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

### Recording retention (Storage tab)

Local source M4A and archived source M4A retention are configured independently. Retention is conservative: when archive verification is ambiguous, audio is kept rather than deleted.

An archived retention value of `0` means **Forever**.

## Recovery behavior

Meeting Transcriber intentionally separates transcription completion from publishing. If publishing fails after a meeting was processed successfully, the completed local run remains available and can be published again without retranscribing.

Folders and saved sessions are also copied to a local backup at app start; run `tools/mt backup --list` to see the copies and `tools/mt backup --restore NAME` to restore one. The backend also supports recovery/resume paths for completed transcripts/summaries when downstream artifact creation failed.

## Data and privacy

Meeting processing is designed to stay local:

- Whisper runs locally.
- Ollama runs locally.
- Meeting/session data is stored in configured local/archive locations.

Normal operation does not require sending transcript content to a hosted model service.
