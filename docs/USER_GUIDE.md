# User Guide

Meeting Transcriber is organized into four workspaces: **Transcribe**, **Meetings**, **Speakers**, and **Search**. For a screen-by-screen tour and how-to recipes, see the [Swift App Guide](SWIFT_APP_GUIDE.md); this page describes behavior.

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

Sessions let you work with a persistent set of meetings instead of asking one-off questions. They live in the Meetings sidebar.

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

Preferences has four tabs. **Storage** and **Local AI** are saved with the **Save** button; **Meetings** and **Voices** settings apply immediately.

- **Storage** — folders and recording retention.
- **Local AI** — backend, model, performance profile and context override.
- **Meetings** — "Recent" window, sort order, list density, sidebar rows and ordering, notices, confirmations, and prompt favorites.
- **Voices** — switch automatic voice recognition on or off, choose how long unnamed voices are remembered, and see recent runs (see [Voice recognition](#voice-recognition-optional)).

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

## Voice recognition (optional)

By default every voice on the call except yours is labeled **Remote**. Voice recognition can learn who people are from their voices and use that to show the real participants of a meeting. It is off by default and runs entirely on your Mac.

**What you need.** The voice models need PyTorch and the pyannote models, which are large, so they live in their own Python environment, separate from the app's. The models are gated: you need a free Hugging Face account and must accept the models' terms once. The app never includes or sends an access token. Tell the app where that environment is with `python3 voice_cli.py set-python PATH_TO_PYTHON`. Setting up the voice environment is a command-line step; naming people can be done in the app (see below) or in Terminal.

**How it learns.** Fingerprints are stored only on your Mac. Naming is always your decision: a voice is named only when it clearly matches one person and nobody else, and a voice with too little speech is left unnamed rather than guessed.

1. **Learn from one-on-ones.** `python3 voice_cli.py enroll` uses your one-on-one recordings, where the remote voice is one known person.
2. **Look at all meetings.** `python3 voice_cli.py identify-all` works out who spoke in each meeting that has not been done yet. `identify-all --redo` redoes every meeting with what has been learned since; names you confirmed by hand are kept.
3. **Name recurring voices.** `python3 voice_cli.py unknowns` lists unnamed voices that keep coming back, grouped across meetings. Listen before you name: `unknowns --clips N` saves short audio clips of group N to `~/voice-clips`, then `unknowns --name N NAME` names the whole group. Group numbers can change after each re-run, so check the list just before naming, and name the highest number first.
4. **Name a voice in one meeting.** `python3 voice_cli.py show RUN` lists the voices in a meeting (`--clips --count 3` saves several clips of each so you can be sure), and `confirm RUN NAME --voice NN` names one. Skip voices you cannot place, and voices with less than a minute of speech: a weak fingerprint can make other matches uncertain. If a name disappears from a meeting after you add a new person, confirm it again.

**Naming people in the app.** Two places let you listen and name:

- **Speakers** (sidebar) lists unnamed voices that keep coming back across meetings, biggest first. Each card has **Listen** (three short clips), a name field with a **Known people** menu, and **Name Group**. Naming asks you to confirm, then names the voice in every meeting in the group and teaches the app what that person sounds like. Groups that may mix more than one person are marked, so listen carefully first.
- **Voices…** in a meeting's header (and **Name Voices in a Meeting** on the Speakers screen) lists every voice in that one meeting, so you can name a voice right after a meeting even if it has not appeared in other meetings yet. It names only the voice you choose. A voice with very little speech can be labeled in that meeting, but the app does not learn from it.

Not every voice is worth naming. On a Speakers card, **Hide for Now** moves the group to a collapsed *Hidden* section to come back to later, and **Don't Track** moves it to *Not tracked* for people you never want to label. Both are remembered per meeting voice only, with no fingerprint saved, and **Bring Back** undoes either one. A hidden or ignored group shows again if a later meeting adds a new voice to it.

After you name someone, the app re-checks your other meetings against what it just learned. This takes seconds and uses the fingerprints it already saved, so it needs no audio and no voice tools (`python3 voice_cli.py rematch` does the same from Terminal). Meetings whose saved fingerprints are gone need `identify-all --redo` instead. Short listening clips are deleted when you leave the Speakers screen or quit the app.

**Turn it on.** In Preferences → Voices, switch on **Recognize voices after each transcription** (or run `python3 voice_cli.py auto on`). After each transcription the app then recognizes the voices in the new meeting. This adds roughly half a minute and never affects the transcript if it fails. The Voices tab shows how many people have a fingerprint and the most recent automatic runs; the same log is printed by `python3 voice_cli.py auto`.

**Participants.** With **List the people who spoke as the meeting's participants** on, the meeting list shows who was actually heard, not names guessed from the title or mentioned in the transcript. Names in the title that were not heard are kept, as lower confidence. Meetings without usable voice data keep their old list. To apply this to existing meetings: `python3 voice_cli.py participants` compares the two methods, `participants-new` previews the change, `participants-new --apply` writes it (`--restore` puts the old lists back), and `tools/mt rebuild-index` refreshes the sidebar.

**When the remote audio was not captured.** If a call was taken on speakerphone, the Remote track is silent and the other voices are only in your Mic track. The meeting is marked "remote not captured" and no voices are named.

**Privacy.** Voice fingerprints are biometric data about other people. They are stored only in the app's Application Support folder with private permissions, and are never saved in meetings, exports, archives or the repository. The fingerprints kept for voices that have no name yet are deleted after six months by default; change this in Preferences → Voices, or choose Never delete. Named people are kept until you delete them. Each meeting's `speakers.json` holds only timings, voice numbers and names. See [Setup & Security](SETUP_AND_SECURITY.md#voice-recognition-optional).

## Recovery behavior

Meeting Transcriber intentionally separates transcription completion from publishing. If publishing fails after a meeting was processed successfully, the completed local run remains available and can be published again without retranscribing.

Folders and saved sessions are also copied to a local backup at app start; run `tools/mt backup --list` to see the copies and `tools/mt backup --restore NAME` to restore one. The backend also supports recovery/resume paths for completed transcripts/summaries when downstream artifact creation failed.

## Data and privacy

Meeting processing is designed to stay local:

- Whisper runs locally.
- Ollama runs locally.
- Meeting/session data is stored in configured local/archive locations.

Normal operation does not require sending transcript content to a hosted model service.
