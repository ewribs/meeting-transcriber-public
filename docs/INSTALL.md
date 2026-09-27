# Installation Guide

This guide describes the current development installation for Meeting Transcriber on Apple Silicon macOS.

## 1. Requirements

Meeting Transcriber currently assumes:

- Apple Silicon Mac.
- macOS with microphone access available to the built app.
- Xcode capable of opening the project under `swift/Meeting Transcriber/`.
- Homebrew.
- Python 3 with `venv` support.
- `ffmpeg` / `ffprobe`.
- `whisper.cpp` and `whisper-cli`.
- Ollama with at least one compatible local model installed.
- A macOS audio input named **Transcribe** exposing at least five input channels if you want to use native recording.

The supported Swift app currently looks for the repository and Python environment at fixed paths:

```text
~/Projects/meeting-transcriber
~/Projects/meeting-transcriber/.venv/bin/python
```

Clone or place the project there unless `BackendService.swift` is changed accordingly.

## 2. Install Homebrew dependencies

Install the external command-line dependencies:

```bash
brew install ffmpeg
brew install whisper-cpp
brew install ollama
```

Verify them:

```bash
ffmpeg -version
ffprobe -version
/opt/homebrew/bin/whisper-cli --help | head
ollama list
```

The backend currently resolves `whisper-cli` at:

```text
/opt/homebrew/bin/whisper-cli
```

## 3. Create the Python environment

From the repository root:

```bash
cd ~/Projects/meeting-transcriber
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The current Python runtime dependency is `Markdown`; most backend code otherwise uses the standard library and external local processes/services.

## 4. Install the Whisper model

The current configuration expects the English medium model here:

```text
~/whisper/models/ggml-medium.en.bin
```

Create the model directory if needed:

```bash
mkdir -p ~/whisper/models
```

Install/download the `whisper.cpp` `medium.en` model using the method supported by your installed `whisper.cpp` version, then verify:

```bash
ls -lh ~/whisper/models/ggml-medium.en.bin
```

The processing pipeline uses approximately five-minute Whisper chunks.

## 5. Install and start Ollama

Start Ollama, then install at least one model that Meeting Transcriber can discover with `ollama list`.

For example:

```bash
ollama pull qwen3:14b
ollama list
```

The repository default is `qwen3:8b`, but the native Preferences UI discovers installed models and lets you select a different local model.

Ollama must respond locally at:

```text
http://localhost:11434
```

## 6. Create local working folders

The legacy/preflight path expects a local `meetings/` directory to exist:

```bash
mkdir -p ~/Projects/meeting-transcriber/meetings
mkdir -p ~/Projects/meeting-transcriber/output
mkdir -p ~/Projects/meeting-transcriber/logs
```

The native app also supports a configurable **Recordings folder** in Preferences. Set that folder before native recording.

## 7. Configure the Transcribe aggregate input

Native recording expects an input device named exactly:

```text
Transcribe
```

The recording contract is:

- Remote audio: aggregate channel 1 (`c0`).
- Microphone audio: aggregate channel 5 (`c4`).
- At least five input channels total.

Use **Audio MIDI Setup** in macOS to create/configure the aggregate device so the remote source and microphone land in those channel positions. The app's Transcribe input monitor reports whether the device exposes the expected five-channel layout.

The finalized meeting recording is a five-channel AAC/M4A preserving the channel order used by the Python transcription pipeline.

## 8. Build the native app

Open:

```text
swift/Meeting Transcriber/Meeting Transcriber.xcodeproj
```

In Xcode:

1. Select the **Meeting Transcriber** scheme.
2. Choose the local Mac as the run destination.
3. Build and Run.
4. Grant microphone permission when prompted.
5. Grant access to configured network/archive volumes when macOS asks.

The app invokes `backend_bridge.py` using `.venv/bin/python` from the repository root.

## 9. First-run Preferences

Open **Meeting Transcriber Settings** and configure:

- Output folder.
- Archive folder / NAS path.
- Recordings folder.
- Ollama model.
- Performance profile.
- Context override if intentionally needed.
- Local and archived source-M4A retention.

Recommended default for performance is **Auto**. Auto detects the Mac's hardware/memory class and resolves to Conservative, Balanced, or High Performance. The Preferences UI shows the resolved profile, effective context, and direct-context budget.

## 10. Validate the backend

With the virtual environment active:

```bash
cd ~/Projects/meeting-transcriber
python preflight.py
```

Preflight checks the local meeting directory, output directory, `ffmpeg`, `whisper-cli`, Whisper model, Ollama service, and selected model.

Run the automated Python suite:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

## Troubleshooting

### The native app says the project or Python environment is missing

Confirm both exist exactly here:

```text
~/Projects/meeting-transcriber
~/Projects/meeting-transcriber/.venv/bin/python
```

### The Transcribe input is missing

Open Audio MIDI Setup and confirm an input device named `Transcribe` exists. The native recorder intentionally selects that name rather than an arbitrary microphone.

### The input monitor works but recording is rejected

The aggregate device must expose at least five channels with Remote on `c0` and Mic on `c4`.

### Ollama model is unavailable

Run:

```bash
ollama list
```

Install the desired model and use **Refresh Models** in Preferences.

### Whisper cannot start

Verify:

```bash
ls -l /opt/homebrew/bin/whisper-cli
ls -lh ~/whisper/models/ggml-medium.en.bin
```

### Archive is unavailable

Mount the configured archive/NAS path, then reopen Preferences or retry the operation. Publishing intentionally refuses unsafe/incomplete archive operations.

## Private local identity configuration

Meeting Transcriber keeps the local user's real name and self-reference aliases out of source control. These values are used to distinguish the local **Mic** speaker from remote participants when extracting participants, commitments, and follow-ups.

Run the interactive setup once after installation:

```bash
python tools/maintenance/configure_identity.py
```

This creates `identity.local.json` in the repository root. The file is intentionally ignored by Git. `identity.example.json` documents the public-safe schema.

If the private file is absent, the application uses generic public-safe defaults (`User` / `Mic`). For accurate participant and commitment attribution, configure the local identity before processing real meetings.
## Optional private business context

The public application works without organization-specific mappings. If you want
stable normalization for private supplier, project, or internal workstream aliases,
copy `business_context.example.json` to `business_context.local.json` and replace the
generic entries with your own values. The local file is Git-ignored and must remain
private. You can validate it with:

```bash
python tools/maintenance/configure_business_context.py
```
