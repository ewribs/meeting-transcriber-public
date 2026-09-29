# Meeting Transcriber

**Turn meetings into searchable memory — locally.**

Meeting Transcriber is a local-first meeting intelligence application for macOS and Apple Silicon. It records or imports meetings, transcribes them with `whisper.cpp`, summarizes them with local Ollama models, and turns the results into searchable meeting memory without sending meeting content to a hosted AI service.

The supported desktop experience is a native **SwiftUI** app. The Swift app delegates transcription, local AI, meeting memory, search, sessions, persistence, publishing, and retention logic to the Python backend in this repository.

## Why this exists

Most meeting assistants are built around hosted transcription and AI services. Meeting Transcriber is designed around a different assumption: meeting audio, transcripts, summaries, and structured memory can stay on your Mac while still supporting useful workflows such as local speech-to-text, AI summarization, meeting search, persistent sessions, and multi-meeting Q&A.

The project combines **SwiftUI**, **Python**, **whisper.cpp**, **Ollama**, and **ffmpeg** into a local-first workflow designed specifically for Apple Silicon.

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

Meeting Transcriber no longer requires one fixed repository path. The macOS
bootstrap records the chosen checkout in Application Support so the Swift app can
find the Python backend wherever you install it.

For a new Mac:

1. Install Apple's Xcode Command Line Tools if needed:

```bash
xcode-select --install
```

2. Install Homebrew manually from [brew.sh](https://brew.sh). Meeting Transcriber's
   setup deliberately does not install Homebrew for you.

3. Clone and bootstrap Meeting Transcriber:

```bash
git clone https://github.com/ewribs/meeting-transcriber-public.git ~/Projects/meeting-transcriber
cd ~/Projects/meeting-transcriber
./tools/setup/bootstrap_macos.sh --dry-run
./tools/setup/bootstrap_macos.sh
```

Fresh installs default to:

- Working: `~/Documents/Meeting Transcriber/Working`
- Meetings / Recordings: `~/Documents/Meeting Transcriber/Meetings`
- Archive: `~/Documents/Meeting Transcriber/Archive`

All three locations are configurable.

The setup is intentionally reviewable. Read [Installation](docs/INSTALL.md) and
[Setup & Security Transparency](docs/SETUP_AND_SECURITY.md) before running it.

The Command Line Tools are sufficient for setup and backend processing of existing
recordings. Full Xcode is required to build and run the native Swift app.

Then:

1. Open `swift/Meeting Transcriber/Meeting Transcriber.xcodeproj` in Xcode.
2. Build and run **Meeting Transcriber**.
3. Review **Settings → Meeting Transcriber Settings**.
4. Use an existing recording immediately, or configure the optional five-channel
   **Transcribe** input if you want native recording.

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
│   ├── query/                   # optional command-line query tools
│   └── setup/                   # transparent macOS install/validation tools
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
- [Setup & Security Transparency](docs/SETUP_AND_SECURITY.md)
- [User Guide](docs/USER_GUIDE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [File Lifecycle & Retention](docs/FILE_LIFECYCLE.md)
- [Changelog](docs/CHANGELOG.md)

## Project status

Meeting Transcriber is an actively developed personal/local application. The Python backend and SwiftUI app are both under active iteration. Treat the current committed branch as the known-good baseline before making substantial pipeline changes.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
