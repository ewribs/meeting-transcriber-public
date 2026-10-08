# Tools

Utilities for developing, maintaining, installing, validating, and releasing Meeting Transcriber.

Manual utilities are intentionally separated from automated tests so test discovery remains side-effect free.

> **Important:** Some tools can operate on real local or archived meeting data. Review a script before running it. Destructive tools are dry-run by default wherever practical.

---

## Recommended entry point: `tools/mt`

For normal development and maintenance work, use the local-only `tools/mt` launcher instead of remembering individual script names.

```bash
tools/mt
```

Interactive menu:

```text
Meeting Transcriber Tools

1. Create source snapshot
2. Build / install local app
3. Run test suite
4. Git status / checkpoint prep
5. Private -> public release sync
6. Audio retention audit
7. Repair legacy audio archives (dry run)
8. Repair legacy audio archives (APPLY)
9. Exit
```

Direct commands are also supported:

```bash
tools/mt snapshot
tools/mt install
tools/mt test
tools/mt status
tools/mt release
tools/mt retention
tools/mt repair
tools/mt repair --apply
```

`tools/mt` is intentionally local-only. It orchestrates tracked utilities plus local private/public release helpers without duplicating their implementation.

### Command mapping

| `tools/mt` command | Underlying tool |
|---|---|
| `snapshot` | `tools/create_source_snapshot.py` |
| `install` | `tools/install_local_app.sh` |
| `test` | Python `unittest` discovery |
| `status` | `git diff --check`, `git status`, `git diff --stat` |
| `release` | `tools/release_sync_local.sh` |
| `retention` | `tools/maintenance/legacy_audio_audit.py` |
| `repair` | `tools/maintenance/repair_legacy_audio_archives.py` |

---

# Directory layout

```text
tools/
├── README.md
├── mt                              # Local-only one-stop launcher
├── build_public_release.py
├── release_audit.py
├── sync_public_release.py
├── install_local_app.sh
├── create_source_snapshot.py       # Local-only helper
├── release_sync_local.sh           # Local-only helper
│
├── backfill/
│   ├── backfill_meeting_memory.py
│   ├── backfill_participants.py
│   ├── backfill_onenote.py
│   └── backfill_onenote_exports.py
│
├── diagnostics/
│   ├── ai_cleanup_smoke.py
│   ├── archive_smoke.py
│   ├── bulk_publisher_smoke.py
│   ├── chunk_transcribe_smoke.py
│   ├── chunking_smoke.py
│   ├── dashboard_smoke.py
│   ├── html_generator_smoke.py
│   ├── indexer_smoke.py
│   ├── llm_smoke.py
│   ├── metadata_smoke.py
│   ├── onenote_copy_smoke.py
│   ├── onenote_export_smoke.py
│   ├── publisher_smoke.py
│   ├── summary_smoke.py
│   └── vtt_merge_smoke.py
│
├── maintenance/
│   ├── cleanup_local_wavs.py
│   ├── cleanup_nas_wavs.py
│   ├── legacy_audio_audit.py
│   ├── repair_legacy_audio_archives.py
│   ├── configure_business_context.py
│   ├── configure_identity.py
│   └── rebuild_html.py
│
├── query/
│   ├── query_meetings.py
│   └── query_meeting_memories.py
│
└── setup/
    ├── bootstrap_macos.sh
    ├── configure_install.py
    ├── validate_install.py
    └── install_from_github.sh
```

Some folders also contain `__init__.py` package markers. Those files contain no operational behavior; they simply keep imports and package structure predictable.

---

# Root-level tracked tools

## `build_public_release.py`

Builds a sanitized public-source release from the private repository.

Typical responsibilities include:

- exporting tracked source from committed Git state;
- excluding local/private state;
- applying public-release transformations;
- preparing a distributable public ZIP;
- invoking release/privacy validation.

This is lower-level release infrastructure. Normal releases should use `sync_public_release.py` through the local release wrapper rather than calling this directly.

---

## `release_audit.py`

Audits the tracked source tree for privacy and public-release problems.

Its purpose is to prevent private or environment-specific data from entering the public project.

The audit focuses on the committed/tracked source surface and can flag suspicious paths, private data patterns, or other release-policy violations.

This is a safety layer for the sanitized public repository.

---

## `sync_public_release.py`

Synchronizes the sanitized private source into the separate public repository.

High-level workflow:

```text
Private Git HEAD
    ↓
Build sanitized candidate
    ↓
Run privacy/release validation
    ↓
Run regression tests on candidate
    ↓
Compare with public repo
    ↓
Dry-run by default
    ↓
--apply copies sanitized changes
    ↓
Validate resulting public repo
```

Key characteristics:

- requires clean source/release state;
- supports dry-run review;
- preserves files explicitly configured for the public repository;
- ignores transient local artifacts;
- validates the sanitized result before and after synchronization.

This script performs the actual source synchronization. The local-only `release_sync_local.sh` adds Git push/commit/review orchestration around it.

---

# Native app installation

## `install_local_app.sh`

Builds and installs the native Swift app for normal Dock use.

```bash
tools/mt install
```

or directly:

```bash
tools/install_local_app.sh
```

Typical workflow:

1. Build the Swift app in Release configuration with `xcodebuild`.
2. Use repository-local DerivedData under `.build/xcode`.
3. Record the current repository path in the app's Application Support configuration so the Swift frontend can find the Python backend.
4. Stage the newly built `.app`.
5. Quit the currently running installed app.
6. Replace the installed copy.
7. Restore the prior copy when possible if replacement fails.
8. Launch the newly installed app unless `--no-launch` is specified.

Default install location:

```text
~/Applications
```

The installer does not package private meeting content or local identity files.

---

# `backfill/`

One-time or occasional historical-data repair tools.

Use these when the data model or extraction logic has changed and older meeting archives need to be brought forward.

## `backfill_meeting_memory.py`

Generates `meeting_memory.json` for older archived meetings that predate the current authoritative-memory pipeline.

Expected source artifacts generally include:

```text
meeting_metadata.json
meeting_transcript_cleaned.md
meeting_summary.md
```

Behavior:

- scans an archive root;
- skips non-meeting folders;
- identifies meetings missing memory;
- runs the current meeting-memory extraction path;
- dry-run by default;
- writes with `--apply`;
- can rebuild existing memory with `--force`.

Use this only when deliberately backfilling historical archives.

---

## `backfill_participants.py`

Re-runs current participant extraction over historical meetings.

Typical behavior:

- reads current meeting metadata;
- reads the cleaned transcript;
- runs current participant extraction;
- compares old and newly detected participant data;
- dry-run by default;
- writes only when explicitly applied.

Useful after participant-identification improvements.

---

## `backfill_onenote.py`

Copies already-existing OneNote exports from archived meetings into the configured OneNote import/landing directory.

This tool **does not generate missing exports**.

Conceptually:

```text
archive/meeting/exports/OneNote_*.html
                ↓
          OneNote import folder
```

Existing destination files are skipped.

---

## `backfill_onenote_exports.py`

Broader OneNote historical repair.

Unlike `backfill_onenote.py`, this tool can:

- detect an existing OneNote export and copy it; or
- generate a missing export using the current pipeline;
- then copy the resulting export to the OneNote import directory.

The two OneNote backfill tools overlap somewhat and are candidates for consolidation during a future repository cleanup.

---

# `diagnostics/`

Manual development smoke tests and local diagnostics.

These are intentionally **not** automated unit tests. Many originated during earlier phases of the project and some are now legacy.

## `ai_cleanup_smoke.py`

Manual smoke test for AI transcript cleanup.

Exercises the transcript-cleaning path, typically through `clean_transcript_in_chunks()`, and writes/prints cleaned output for manual inspection.

---

## `archive_smoke.py`

Manual test of meeting archiving.

Exercises the archive path for an already processed meeting.

---

## `bulk_publisher_smoke.py`

Manual test of bulk publishing multiple meetings.

Exercises the bulk-publish workflow.

---

## `chunk_transcribe_smoke.py`

Low-level Whisper chunk-transcription sanity test.

Useful for isolating transcription/backend problems from the rest of the meeting pipeline.

---

## `chunking_smoke.py`

Tests transcript chunking.

Loads transcript text, runs the chunking logic, and reports resulting chunk boundaries/content.

Useful when investigating context-window or chunk-size behavior.

---

## `dashboard_smoke.py`

Exercises the older dashboard-generation code.

This belongs to the legacy HTML/browser presentation stack and is a future cleanup candidate.

---

## `html_generator_smoke.py`

Exercises transcript and summary HTML generation.

Typically validates functions such as:

- `build_transcript_html()`
- `build_summary_html()`

Also part of the older HTML presentation path.

---

## `indexer_smoke.py`

Exercises the historical meeting-index generator.

Used by the older browser/dashboard experience.

Likely a cleanup candidate now that SwiftUI is the primary frontend.

---

## `llm_smoke.py`

Small direct LLM sanity test.

Useful for quickly checking that the Python backend can invoke the configured language model without running a full meeting.

---

## `metadata_smoke.py`

Manual test of meeting metadata creation.

Useful for isolating metadata-generation logic.

---

## `onenote_copy_smoke.py`

Manual test of copying a prepared OneNote export into the import/landing folder.

---

## `onenote_export_smoke.py`

Manual test of generating a OneNote-friendly summary export.

---

## `publisher_smoke.py`

Manual test of publishing a single processed meeting.

---

## `summary_smoke.py`

Manual test of meeting summarization, including the older/chunked summarization path.

Useful for debugging summary generation without running the full application workflow.

---

## `vtt_merge_smoke.py`

Tests merging chunk-level Whisper VTT output into a single chronological VTT.

Useful for transcription pipeline debugging.

---

## Diagnostics cleanup status

The diagnostics directory contains a mixture of:

- still-useful manual probes;
- logic that should eventually become automated regression coverage;
- older HTML/dashboard tooling that may now be obsolete.

A future cleanup pass should classify each script as:

```text
KEEP
CONVERT TO REGRESSION TEST
ARCHIVE
DELETE
```

---

# `maintenance/`

Operational maintenance, cleanup, archive, and local-configuration utilities.

This is one of the most actively useful tool directories.

## `cleanup_local_wavs.py`

Removes intermediate WAV files from local processed-meeting runs **only after verifying that the meeting is safely archived**.

Typical eligibility requires a complete corresponding archive containing required derived artifacts such as:

```text
meeting_summary.md
meeting_transcript_cleaned.md
meeting_metadata.json
meeting_memory.json
```

Behavior:

- dry-run by default;
- `--delete` performs deletion;
- skips unarchived or incomplete meetings;
- reports reclaimable storage.

This targets large temporary split-channel WAV files created during processing.

---

## `cleanup_nas_wavs.py`

Removes intermediate WAV files that were copied into completed NAS meeting archives.

Behavior:

- scans normal archive meeting folders;
- ignores non-meeting areas such as recycle/import/session folders;
- validates archive completeness;
- reports reclaimable WAVs;
- dry-run by default;
- `--delete` removes them;
- removes empty `audio/` directories where possible.

This is archive-side WAV cleanup.

---

## `legacy_audio_audit.py`

Read-only audio-lifecycle audit.

Recommended invocation:

```bash
tools/mt retention
```

This tool does **not** modify anything.

It reports several categories:

### Active local meeting WAVs

Intermediate WAVs still present in local processing runs.

### Development / Pilot WAVs

Tracked separately so experimental recordings are not accidentally treated as normal app-managed reclaimable data.

### Active archive WAVs

Intermediate WAVs still stored in normal meeting archives.

### Synology recycle-bin WAVs

Files under Synology recycle storage are shown for visibility only. Their retention/purge policy belongs to Synology, not Meeting Transcriber.

### Local M4As

For local recordings older than the configured retention period, each recording is classified as:

```text
safe to remove
blocked from removal
```

A local M4A is only considered safe when the archive relationship can be verified conservatively.

Typical blocking reasons include:

- no matching archive;
- multiple matching archives;
- incomplete archive;
- archived source M4A missing;
- archived source M4A size mismatch.

### Archived source M4As

Also reports archived M4As that have crossed the configured archive-retention threshold.

### Summary

Provides file counts and storage totals, including:

```text
App-managed reclaimable audio
```

This is the primary manual diagnostic for audio retention.

---

## `repair_legacy_audio_archives.py`

Backfills original source M4As into older archives created before source-audio archival was introduced.

Recommended invocation:

```bash
tools/mt repair
```

Dry-run is the default.

Apply mode:

```bash
tools/mt repair --apply
```

A recording is repairable only when the tool can identify **exactly one complete matching archive** and no conflicting archived source exists.

When applying a repair, the tool:

1. creates the archive `source/` folder if needed;
2. copies the local original M4A;
3. verifies file size;
4. verifies SHA-256;
5. removes an invalid copy if verification fails.

The tool does **not** delete the local original.

It deliberately refuses:

- no-match cases;
- multiple-match cases;
- incomplete archives;
- conflicting existing archived source files.

After repair, normal retention can safely remove the local copy once it exceeds the configured retention period.

---

## `configure_business_context.py`

Creates or validates private local business-context configuration used by the application.

This is intended for environment-specific context that should remain outside the tracked/public source tree.

---

## `configure_identity.py`

Creates or updates private local identity/person configuration.

This keeps local identity mapping separate from public source and avoids hard-coding personal identity into the application.

---

## `rebuild_html.py`

Historical utility for rebuilding:

```text
meeting_transcript.html
meeting_summary.html
```

from Markdown artifacts.

This tool currently reflects older HTML-era workflows and is a cleanup candidate. If retained, it should be generalized/parameterized rather than depending on one historical path or use case.

---

# `query/`

Optional command-line access to the cross-meeting query and Sessions engine.

Normal users can now access much of this functionality through the SwiftUI app, but the CLI remains valuable for debugging the Python source of truth.

## `query_meetings.py`

Simple free-form query tool over one or more explicit meeting directories.

Typical conceptual flow:

```text
selected meeting directories
        ↓
load meeting summaries
        ↓
send combined context to LLM
        ↓
print response
```

This is the simpler/older query interface and does not provide the richer persistent Sessions workflow.

---

## `query_meeting_memories.py`

Richer CLI over authoritative `meeting_memory.json`.

Supports functionality such as:

- explicit meeting selection;
- participant filtering;
- date filtering;
- topic filtering;
- selected-meeting listing;
- interactive selection;
- multi-turn chat;
- workbench behavior;
- persistent named sessions;
- session resume;
- session refresh using saved criteria;
- session listing;
- session display;
- rename;
- delete.

This CLI is an entry point only. The actual session/query implementation lives in the top-level runtime `query/` package.

---

# `setup/`

macOS installation, bootstrap, and validation helpers.

These are designed to make the public project transparent and reproducible on another Mac.

## `configure_install.py`

Writes local installation configuration.

Typical responsibilities include configuring:

- repository path;
- working/output directory;
- archive directory;
- recording directory;
- model settings.

It uses the application's own configuration modules rather than maintaining a parallel config format.

It may back up existing local configuration before changing it.

It does not install Homebrew, download arbitrary remote scripts, or launch background services.

---

## `validate_install.py`

Read-only install-health diagnostic.

Checks installation/runtime prerequisites and reports PASS/WARN/FAIL.

Depending on configuration it can inspect items such as:

- Python runtime;
- project virtual environment;
- configured directories;
- install metadata;
- LLM dependencies;
- Ollama availability/models;
- Whisper installation/model;
- native/recording prerequisites;
- optional regression tests.

It does not change configuration.

---

## `bootstrap_macos.sh`

Transparent macOS bootstrap script.

Supports dry-run/check behavior and can help prepare a fresh Mac installation.

Typical responsibilities include:

- validate Xcode command-line tools;
- validate Homebrew;
- create/configure Python environment;
- install required Python dependencies;
- prepare Whisper;
- prepare/configure local LLM dependencies;
- configure working/archive/recording paths;
- run validation/tests;
- optionally build the native Swift app.

It intentionally avoids opaque remote execution patterns.

---

## `install_from_github.sh`

Public installation entry point.

Typical flow:

```text
clone public repository
      or
git pull --ff-only
        ↓
bootstrap_macos.sh
```

This is intended as a simple installation path for a clean/public environment.

---

# Local-only development helpers

These helpers are intentionally excluded from Git/public release.

## `create_source_snapshot.py`

Creates a source ZIP for development handoff and review.

Recommended invocation:

```bash
tools/mt snapshot
```

Typical output:

```text
dist/meeting-transcriber-source-YYYYMMDD-HHMMSS-<gitsha>.zip
```

This is the preferred way to create a fresh authoritative source snapshot for development work.

---

## `release_sync_local.sh`

High-level private-to-public release orchestrator.

Recommended invocation:

```bash
tools/mt release
```

Workflow:

```text
verify private repo clean
        ↓
verify public repo clean
        ↓
optional private regression suite
        ↓
sanitized public dry-run
        ↓
push private repo
        ↓
confirm
        ↓
apply sanitized public sync
        ↓
show public status / diff / stat
        ↓
confirm
        ↓
enter PUBLIC-SAFE title/body
        ↓
commit public repo
        ↓
push public repo
```

Important privacy behavior:

- public commit text is **never automatically copied from private Git history**;
- public diff is reviewed before commit;
- public commit title/body must be explicitly approved;
- the prompt validates against obvious accidental labels/leading prompt characters.

The tracked source synchronization engine remains:

```text
tools/sync_public_release.py
```

while `release_sync_local.sh` is the local orchestration layer.

---

# Runtime maintenance related to tools

## `startup_maintenance.py`

This file is part of the application runtime rather than `tools/`, but it is directly related to maintenance.

At app startup, the Swift frontend invokes backend startup maintenance so configured audio retention can run automatically.

Conceptual flow:

```text
App launches
    ↓
Swift calls backend startup maintenance
    ↓
Python reads configured retention settings
    ↓
safe local M4As are evaluated/purged
    ↓
archive retention is evaluated
    ↓
maintenance failure is reported/logged
    ↓
app launch continues
```

This automated startup path complements the manual maintenance tools.

`legacy_audio_audit.py` remains the read-only way to see what the retention engine considers safe or blocked.

---

# Audio lifecycle workflow

Current intended behavior:

```text
Record meeting
    ↓
Local M4A created
    ↓
Transcription/processing
    ↓
Publish & Archive
    ↓
Original source M4A copied to archive/source/
    ↓
Archive/source relationship verified
    ↓
Local M4A retained for configured local period
    ↓
Startup maintenance or post-publish maintenance
    ↓
Old verified local M4A deleted
```

Legacy archives that predate source-M4A archival can be repaired with:

```bash
tools/mt repair
tools/mt repair --apply
```

Then checked with:

```bash
tools/mt retention
```

Intermediate WAV cleanup remains separate from source-M4A retention.

---

# Public/private release workflow

Recommended release workflow:

```bash
# 1. Validate/checkpoint private work
tools/mt status

# 2. Commit private changes
git add ...
git commit -m "..."

# 3. Run the release orchestrator
tools/mt release
```

Under the hood:

```text
Private repository
       ↓
release_sync_local.sh
       ↓
sync_public_release.py
       ↓
build_public_release.py
       ↓
release_audit.py
       ↓
Sanitized public repository
```

The public repository must never include:

- real/internal meeting names;
- real participant names from private meetings;
- transcript excerpts;
- private benchmark data;
- internal run-folder names;
- local identity configuration;
- private business context;
- private release manifests;
- other sensitive/local environment state.

Tracked regression fixtures should use generic public-safe entities and examples.

---

# Current maturity / cleanup notes

## Primary/current tools

These are active and should be considered part of the normal workflow:

```text
tools/mt
install_local_app.sh
sync_public_release.py
release_audit.py
build_public_release.py
legacy_audio_audit.py
repair_legacy_audio_archives.py
setup/*
```

Local-only primary helpers:

```text
create_source_snapshot.py
release_sync_local.sh
```

## Occasional but valid

```text
backfill/*
query/*
cleanup_local_wavs.py
cleanup_nas_wavs.py
configure_business_context.py
configure_identity.py
```

## Cleanup candidates

The biggest cleanup opportunity is `diagnostics/`.

Some diagnostics remain useful, but others reflect earlier HTML/browser-era architecture.

`rebuild_html.py` is also a clear cleanup/generalization candidate.

The OneNote backfill utilities overlap and may be consolidated.

A future repository cleanup pass should review each legacy script and classify it as:

```text
KEEP
CONVERT TO AUTOMATED TEST
CONSOLIDATE
ARCHIVE
DELETE
```

---

# Quick reference

### One-stop launcher

```bash
tools/mt
```

### Source snapshot

```bash
tools/mt snapshot
```

### Build/install native app

```bash
tools/mt install
```

### Full Python tests

```bash
tools/mt test
```

### Git/checkpoint status

```bash
tools/mt status
```

### Private → public release

```bash
tools/mt release
```

### Read-only audio lifecycle audit

```bash
tools/mt retention
```

### Legacy archive repair preview

```bash
tools/mt repair
```

### Apply safe legacy archive repairs

```bash
tools/mt repair --apply
```

---

# Safety principles

1. **Dry-run first.**
2. **Never weaken archive verification to force deletion.**
3. **Do not delete a local source recording unless a safe archive relationship is verified.**
4. **Do not treat Synology recycle-bin contents as app-managed cleanup.**
5. **Do not put private meeting information into tracked/public source, tests, docs, fixtures, release metadata, or comments.**
6. **Keep local identity/business configuration outside public source.**
7. **Review public diffs before commit and push.**
8. **Prefer `tools/mt` for routine work; invoke lower-level scripts directly when debugging or performing specialized maintenance.**

---

# Private memory benchmark harness

`tools/benchmark/memory_benchmark.py` replays cleaned meeting artifacts through the
current meeting-memory pipeline without rerunning Whisper or the GUI. It is intended
to make memory-quality changes measurable before they are promoted into production.

Private benchmark inputs and generated results are intentionally excluded from Git:

```text
private_benchmarks/
benchmark_runs/
```

Do not place real meeting transcripts, participant names, suppliers, projects, or
other private meeting content in tracked tests, fixtures, docs, examples, or release
artifacts. The committed unit tests for the harness use sanitized examples only.

## Create a private case from an existing meeting run

From the repository root:

```bash
python tools/benchmark/memory_benchmark.py init \
  --source /path/to/existing/meeting/run \
  --case my-private-case
```

This copies only:

```text
meeting_metadata.json
meeting_summary.md
meeting_transcript_cleaned.md
```

into `private_benchmarks/my-private-case/` and creates an editable
`expected_memory.json` gold file. Audio and Whisper output are not copied or rerun.

Edit the gold file so it contains only the durable memory that a human reviewer
expects the meeting to retain. Each expected item can match on owner plus required,
alternative, excluded, or regex text terms. Empty expected categories mean any
prediction in that category counts as a false positive.

## Run one private case

```bash
python tools/benchmark/memory_benchmark.py run --case my-private-case
```

Run the full local corpus:

```bash
python tools/benchmark/memory_benchmark.py run --all
```

Each run writes a timestamped local result folder under `benchmark_runs/` containing:

```text
actual_memory.json
memory_trace.json
processing_diagnostics.json
benchmark_result.json
benchmark_report.md
```

`memory_trace.json` captures the memory pipeline stages only while the benchmark is
running: per-window proposals and grounded events, merged events, the participant
identity map, pass-2 proposals, owner-resolution state, final validator rejections,
verified results, and final reconciled memory. Normal app processing leaves this
trace disabled and does not retain the extra meeting content.

The benchmark reports per-category precision and recall for Actions, Decisions,
Risks, and Open Questions. The default gold template requires 100% precision and
100% recall; thresholds may be relaxed explicitly in a private case when needed.
Channel labels such as `Remote` and `Mic` can also be listed as forbidden owners.

## Score an already-generated memory file without calling the LLM

```bash
python tools/benchmark/memory_benchmark.py score \
  --actual /path/to/meeting_memory.json \
  --expected private_benchmarks/my-private-case/expected_memory.json
```

This is useful when tuning the gold file or reviewing an archived result.
