# Installation Guide

Meeting Transcriber supports Apple Silicon macOS and is designed to run its
transcription and AI workloads locally.

For a line-by-line explanation of what setup changes and what it contacts, read
[Setup & Security Transparency](SETUP_AND_SECURITY.md) before running anything.

## Recommended installation flow

The public project is designed to support a review-first setup:

1. Obtain the public repository or download the small GitHub installer script.
2. Read the setup scripts.
3. Run `--dry-run`.
4. Run the bootstrap.
5. Build the native app in Xcode.
6. Validate with an existing recording; the native multi-channel microphone setup
   is optional unless you want to record directly in Meeting Transcriber.

## Option A — clone the public repository yourself

```bash
git clone https://github.com/ewribs/meeting-transcriber-public.git ~/Projects/meeting-transcriber
cd ~/Projects/meeting-transcriber
less tools/setup/bootstrap_macos.sh
./tools/setup/bootstrap_macos.sh --dry-run
./tools/setup/bootstrap_macos.sh
```

The install directory is no longer required to be
`~/Projects/meeting-transcriber`; that is simply a convenient example/default.

## Option B — reviewed GitHub clone helper

`tools/setup/install_from_github.sh` can clone the public repository into a
chosen directory and then run the same bootstrap. If using a copy of that script
outside an existing checkout, inspect it before running it.

Example:

```bash
bash install_from_github.sh \
  --install-dir "$HOME/Projects/meeting-transcriber" \
  --dry-run
```

Then rerun without `--dry-run` when satisfied.

## What the bootstrap configures

The main script can configure:

- project/repository location;
- Working/output folder;
- Archive folder or NAS path;
- Meetings / Recordings folder;
- Ollama model.

Interactive setup offers defaults. The same values can be supplied explicitly:

```bash
./tools/setup/bootstrap_macos.sh \
  --working-dir "$HOME/Documents/Meeting Transcriber/Working" \
  --archive-dir "/Volumes/Transcribe" \
  --recordings-dir "$HOME/Documents/Meeting Transcriber/Meetings" \
  --llm-model "qwen3:8b"
```

For scripted/headless setup, add `--non-interactive`.

## System prerequisites

Bootstrap expects:

- Apple Silicon macOS;
- Apple's Xcode Command Line Tools;
- Homebrew.

If Command Line Tools are missing, setup launches Apple's installer and asks you
to rerun afterward.

Homebrew is intentionally **not** installed automatically. If it is missing,
setup stops and points you to `https://brew.sh` so you can inspect/install that
third-party bootstrap yourself.

## Dependencies installed through Homebrew

The bootstrap checks/installs these explicit formulas:

```text
python@3.13
ffmpeg
whisper.cpp
ollama
```

It then creates `.venv` under the repository and installs the Python requirements
from `requirements.txt`.

## Whisper

Meeting Transcriber currently expects:

```text
whisper-cli: /opt/homebrew/bin/whisper-cli
model:       ~/whisper/models/ggml-medium.en.bin
```

When the model is missing, setup downloads it directly from the documented
`ggerganov/whisper.cpp` Hugging Face model repository. The URL is printed before
the download begins.

The transcription pipeline continues to use approximately five-minute Whisper
chunks.

## Ollama

Ollama must respond locally at:

```text
http://localhost:11434
```

If it is installed but not responding, setup runs the visible command:

```bash
brew services start ollama
```

The selected model is then installed with `ollama pull` unless
`--skip-model-pull` is supplied.

The repository default is `qwen3:8b`. The native Preferences UI can select any
compatible model discovered through `ollama list`.

## Configurable paths and install metadata

Setup writes local configuration under:

```text
~/Library/Application Support/Meeting Transcriber/
```

`install.json` records the repository location so the Swift app can find the
Python backend from an arbitrary install directory.

`settings.json` contains application preferences including Working, Archive,
Meetings / Recordings, model, performance profile, and retention values.

Existing files are backed up before setup changes them.

The Swift backend path resolution order is:

1. explicit `MEETING_TRANSCRIBER_PROJECT_DIR` environment variable;
2. the path in Application Support `install.json`;
3. historical fallback `~/Projects/meeting-transcriber`.

## Native recording / Audio MIDI Setup

Native recording expects an input device named exactly:

```text
Transcribe
```

The five-channel contract is:

- Remote audio: aggregate channel 1 (`c0`).
- Microphone audio: aggregate channel 5 (`c4`).
- At least five input channels total.

This hardware is **not required to validate the rest of the application**. A
headless or secondary Mac can process existing M4A files without Scarlett/mic
hardware. Setup validation therefore treats a missing `Transcribe` device as a
warning.

## Build the native app

Open:

```text
swift/Meeting Transcriber/Meeting Transcriber.xcodeproj
```

In Xcode:

1. Select the **Meeting Transcriber** scheme.
2. Choose the local Mac as the destination.
3. Build and Run.
4. Grant permissions when macOS requests them.
5. Review **Meeting Transcriber Settings** and confirm storage/model/profile.

If full Xcode is already installed and selected, bootstrap can also perform a
command-line build:

```bash
./tools/setup/bootstrap_macos.sh --build-swift
```

## Validate the installation

Read-only validation:

```bash
./tools/setup/bootstrap_macos.sh --check
```

Or directly:

```bash
.venv/bin/python tools/setup/validate_install.py --run-tests
```

The validator checks the project path, virtualenv, ffmpeg/ffprobe, whisper-cli,
Whisper model, Ollama API/model, storage paths, backend import, Xcode project,
and optional Transcribe audio device.

## Run the Python test suite directly

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

## Private local context

Optional user identity and business vocabulary stay out of Git:

- `identity.local.json`
- `business_context.local.json`
- `known_people.local.json` / `known_people.json`

Example templates remain in the repository. These local files are not created
with personal content automatically by the installer.

## Troubleshooting

### App says project or Python environment is missing

Check:

```text
~/Library/Application Support/Meeting Transcriber/install.json
<configured-project>/.venv/bin/python
```

You can temporarily override the project location when launching from a shell:

```bash
export MEETING_TRANSCRIBER_PROJECT_DIR="/path/to/meeting-transcriber"
```

### Archive is unavailable

If the archive points to `/Volumes/...`, mount that volume/NAS. Setup deliberately
does not create a fake local mount directory when the expected volume is absent.

### Ollama model is unavailable

```bash
ollama list
ollama pull qwen3:8b
```

Then use **Refresh Models** in Preferences.

### Whisper cannot start

```bash
which whisper-cli
ls -lh ~/whisper/models/ggml-medium.en.bin
```

### Native recording input is missing

Only the native recording workflow needs the `Transcribe` aggregate input. You
can still test the rest of the app by adding an existing compatible recording.


### Fresh-install model default

When no existing Meeting Transcriber settings are present, bootstrap selects the initial Ollama model conservatively from detected unified memory: 32 GB or more defaults to `qwen3:14b`; smaller Macs default to `qwen3:8b`. Existing installations keep their configured model unless the user explicitly chooses another one.
