# Meeting Transcriber

Meeting Transcriber is a local-first macOS application for recording, transcribing, summarizing, searching, and revisiting meetings without sending meeting content to a hosted AI service.

The supported desktop experience is the native **SwiftUI** app under `swift/Meeting Transcriber/`. The Swift app delegates transcription, local AI, meeting memory, search, sessions, persistence, publishing, and retention logic to the Python backend in this repository.

## What it does

- Records meetings from a macOS aggregate input named **Transcribe**.
- Preserves a five-channel audio contract with **Remote = channel 1 / c0** and **Mic = channel 5 / c4**.
- Transcribes locally with `whisper.cpp` in approximately five-minute chunks.
- Cleans and summarizes transcripts with a local Ollama model.
- Produces Markdown, HTML, metadata, and structured `meeting_memory.json` artifacts.
- Browses unpublished and archived meetings in a native Meetings workspace.
- Creates saved Sessions with persistent conversation history and local multi-meeting Q&A.
- Supports global Search across meetings and sessions.
- Publishes completed meetings to a configurable archive/NAS, including verified source-audio archival and retention controls.
- Adapts local-AI execution through Auto / Conservative / Balanced / High Performance profiles.

## Current architecture

```text
SwiftUI app
    |
    v
backend_bridge.py
    |
    +-- transcription / summary / meeting memory
    +-- meetings / sessions / search
    +-- preferences / performance profiles
    +-- publishing / archive / retention
    |
    v
Local dependencies
    +-- whisper.cpp
    +-- Ollama
    +-- ffmpeg / ffprobe
```

**Design rule:** Swift owns the native application experience. Python remains the source of truth for meeting-processing and data behavior.

See [Architecture](docs/ARCHITECTURE.md) for details.

For privacy-safe sharing and public-release preparation, see the [Public Release Privacy Guide](docs/PUBLIC_RELEASE.md). A repeatable sanitized export can be built with `python tools/build_public_release.py`.

## Quick start

This project currently expects to live at:

```text
~/Projects/meeting-transcriber
```

That path is used by the native app when launching the Python backend.

1. Follow the full [Installation Guide](docs/INSTALL.md).
2. Open `swift/Meeting Transcriber/Meeting Transcriber.xcodeproj` in Xcode.
3. Build and run **Meeting Transcriber**.
4. Open **Settings → Meeting Transcriber Settings** and configure storage, Ollama model, performance profile, and retention.
5. Verify the **Transcribe** input monitor sees the expected five-channel device before recording.

## Workspaces

The app exposes four primary workspaces:

- **Transcribe** — record a meeting or queue existing recordings for transcription and analysis.
- **Meetings** — browse, review, publish, archive, delete, and query individual meetings.
- **Sessions** — maintain saved multi-meeting contexts and persistent conversations.
- **Search** — search structured meeting/session content and jump directly to results.

See the [User Guide](docs/USER_GUIDE.md).

## Repository layout

```text
meeting-transcriber/
├── README.md
├── *.py                         # production Python backend modules
├── query/                       # multi-meeting query engine
├── tests/                       # automated Python regression suite
├── tools/
│   ├── backfill/                # one-off historical backfills
│   ├── diagnostics/             # manual smoke/diagnostic scripts
│   ├── maintenance/             # maintenance/audit utilities
│   └── query/                   # optional command-line query tools
├── swift/Meeting Transcriber/   # supported native macOS app
├── legacy/qt/                   # retired PySide/Qt front end
└── docs/
    ├── INSTALL.md
    ├── USER_GUIDE.md
    ├── ARCHITECTURE.md
    ├── DEVELOPMENT.md
    └── FILE_LIFECYCLE.md
```

## Tests

From the repository root:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

The `tests/` directory contains automated regression tests only. Manual smoke scripts live under `tools/diagnostics/` and are intentionally excluded from discovery.

See [Development](docs/DEVELOPMENT.md) for test and contribution guidance.

## Documentation

- [Installation Guide](docs/INSTALL.md)
- [User Guide](docs/USER_GUIDE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [File Lifecycle & Retention](docs/FILE_LIFECYCLE.md)
- [Changelog](docs/CHANGELOG.md)

## Project status

Meeting Transcriber is an actively developed personal/local application. The Python backend and SwiftUI app are both under active iteration. Treat the current committed branch as the known-good baseline before making substantial pipeline changes.
