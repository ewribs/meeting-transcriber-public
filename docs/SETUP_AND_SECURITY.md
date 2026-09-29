# Setup & Security Transparency

Meeting Transcriber is a local-first application. The setup tooling is designed
so a reviewer can understand every material change before running it.

## Principles

The setup scripts intentionally follow these rules:

- No downloaded executable script is piped directly into `bash` or `sh`.
- Homebrew's own installer is **not** executed automatically; if Homebrew is
  missing, setup stops and directs you to `https://brew.sh` to review/install it.
- No meeting audio, transcript, summary, or meeting-memory content is uploaded by
  the installer.
- No hidden background jobs are launched. If Ollama is not running, setup uses
  the visible command `brew services start ollama`.
- No `sudo` command is issued by Meeting Transcriber's setup scripts.
- Existing Meeting Transcriber settings/install metadata are backed up before
  setup modifies them.
- Network downloads and their destinations are printed before they occur.
- `--dry-run` shows planned setup actions without changing the machine.
- `--check` performs read-only validation.

The scripts are ordinary text files under `tools/setup/` and are intended to be
read before use.

## Setup files

### `tools/setup/install_from_github.sh`

Optional first-stage installer. It:

1. identifies the public Git repository and requested install directory;
2. clones the repository if the directory does not exist;
3. leaves an existing checkout unchanged unless `--update` is supplied; and
4. hands off to `tools/setup/bootstrap_macos.sh`.

It does not install system packages itself.

### `tools/setup/bootstrap_macos.sh`

Main macOS bootstrap. It checks the required local commands first and uses Homebrew only when a required dependency is missing:

- Python 3.13
- ffmpeg / ffprobe
- whisper.cpp / `whisper-cli`
- Ollama

For `whisper-cli`, ffmpeg/ffprobe, and Ollama, a functional executable is treated as installed even if Homebrew's receipt metadata differs. This avoids unnecessary reinstall proposals on working Macs.

It also:

- creates `.venv` in the repository;
- installs Python dependencies from `requirements.txt`;
- downloads the configured Whisper model if it is missing;
- starts Ollama with Homebrew services if the local API is not responding;
- pulls the explicitly displayed Ollama model unless `--skip-model-pull` is used;
- creates configured storage directories where safe;
- writes local application settings and install metadata;
- runs the Python regression suite unless `--skip-tests` is used; and
- can optionally run an Xcode command-line build with `--build-swift`.

### `tools/setup/configure_install.py`

A small, local-only configuration writer. It does not use the network or install
software. It writes two files under:

```text
~/Library/Application Support/Meeting Transcriber/
```

- `install.json` — repository location used by the Swift app to find the Python backend.
- `settings.json` — application preferences such as storage folders and local model.

If these files already exist, setup keeps `.bak` backups before changing them.

### `tools/setup/validate_install.py`

Read-only diagnostics. It reports PASS/WARN/FAIL for the runtime, model, storage,
backend import, Xcode project, and optional `Transcribe` audio device.

## Network access during setup

Depending on what is already installed, setup may contact:

| Destination | Purpose |
| --- | --- |
| GitHub public repository | Clone/update Meeting Transcriber source. |
| Homebrew package repositories | Install declared command-line dependencies. |
| `huggingface.co/ggerganov/whisper.cpp` | Download `ggml-medium.en.bin` when missing. |
| Ollama model registry | `ollama pull` for the model selected during setup. |
| `localhost:11434` | Check the local Ollama API. This is local machine traffic. |

The installer prints these actions rather than hiding them.

## Existing installations and idempotence

Setup is designed to be safe to rerun. If `settings.json` already exists, non-empty current values for Working, Meetings / recordings, Archive, and the Ollama model become the proposed defaults. Explicit command-line options still override them. Generic fresh-install defaults are used only for values that are not already configured.

On a fresh installation, the model default is selected conservatively from unified memory using the same current memory tiers as the app's Auto performance-profile policy: Macs with at least 32 GB default to `qwen3:14b`; smaller Macs default to `qwen3:8b`. This only chooses the initial model. Runtime context/chunking behavior remains controlled by the Python performance-profile code.

Already-present storage directories, Whisper model files, functional local commands, and an installed selected Ollama model are kept rather than recreated or redownloaded.

## Storage paths

Setup keeps code and user data conceptually separate. The following are
configurable:

- **Project directory** — the Git checkout containing the app/backend source.
- **Working directory** — local processing/output artifacts.
- **Meetings / recordings directory** — configurable folder used for existing recordings and recordings created by the native app. The backend's internal `meetings/` compatibility directory remains inside the project checkout and is not a separate setup choice.
- **Archive directory** — published meeting archive, which may be local or a NAS mount.

The native Swift app no longer needs the repository to live at one fixed path.
It resolves the project location in this order:

1. `MEETING_TRANSCRIBER_PROJECT_DIR` environment variable, when explicitly set;
2. `install.json` written by setup; then
3. the historical `~/Projects/meeting-transcriber` fallback.

## `/Volumes` safety

If a configured path begins with `/Volumes/`, bootstrap checks that the volume is
actually mounted before creating subdirectories. It will not create a misleading
local directory under an absent NAS/removable-volume mount point.

An unavailable archive is allowed as a warning so a laptop/headless Mac can be
configured before the NAS is mounted. Publishing still requires the archive to
be available.

## Homebrew policy

Meeting Transcriber does not bootstrap Homebrew automatically. Homebrew's
installation mechanism is third-party remote code, so users are directed to the
official Homebrew site and can inspect/install it themselves. Once `brew` exists,
the Meeting Transcriber script runs explicit, visible `brew install` commands for
the declared dependencies.

## Whisper model download

The current Whisper model is downloaded directly to:

```text
~/whisper/models/ggml-medium.en.bin
```

from the documented whisper.cpp model repository on Hugging Face. A partial
`.part` file is used and renamed only after the download completes.

## Ollama

Ollama stays local and is expected at:

```text
http://localhost:11434
```

Setup does not send meeting content to a hosted AI endpoint. Pulling an Ollama
model necessarily downloads model files from the Ollama registry.

## Native recording is optional during setup

A macOS aggregate input named `Transcribe` is required only for Meeting
Transcriber's native five-channel recording workflow. A machine without that
device can still install, build, transcribe existing recordings, summarize,
search, query, and publish meetings.

The validator therefore reports a missing `Transcribe` device as a warning, not
an installation failure.

## Reviewing before running

Recommended first pass:

```bash
less tools/setup/bootstrap_macos.sh
less tools/setup/configure_install.py
less tools/setup/validate_install.py
./tools/setup/bootstrap_macos.sh --dry-run
```

After installation:

```bash
./tools/setup/bootstrap_macos.sh --check
```

## Removing setup-created configuration

Meeting Transcriber setup metadata lives under:

```text
~/Library/Application Support/Meeting Transcriber/
```

Removing that directory removes local Meeting Transcriber settings/install
metadata. It does **not** uninstall Homebrew packages, Ollama models, the Whisper
model, the Git checkout, meeting data, or archive data. Those are intentionally
left under the user's control and should be removed separately only when desired.
