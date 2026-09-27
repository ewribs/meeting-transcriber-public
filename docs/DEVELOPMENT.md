# Development Guide

## Development principles

1. Python remains the backend/source of truth.
2. Keep Swift focused on native presentation, navigation, capture, and user interaction.
3. Prefer extending existing services over creating parallel implementations.
4. Use small feature slices: **Inspect → Change → Test → Commit**.
5. Treat a committed green revision as the known-good baseline before pipeline work.
6. Do not change Whisper chunking, model/profile behavior, or summary/memory architecture without evidence and targeted regression coverage.

## Python environment

```bash
cd ~/Projects/meeting-transcriber
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Automated Python tests

The supported automated suite lives entirely in `tests/`:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

Manual scripts must not be named `test_*.py` or live in `tests/`. This prevents `unittest` discovery from accidentally publishing meetings, writing files, calling Whisper/Ollama, or otherwise performing real operations.

### Targeted tests

During feature work, run the smallest relevant test modules first, then the complete suite before committing.

Examples:

```bash
python -m unittest -v tests.test_performance_profile tests.test_backend_bridge
python -m unittest -v tests.test_runtime_summary_integration tests.test_grounded_extraction
```

## Swift validation

Open:

```text
swift/Meeting Transcriber/Meeting Transcriber.xcodeproj
```

Build the **Meeting Transcriber** target and run the available unit/UI tests from Xcode. Python tests do not replace a native build when Swift files changed.

## Tools

### Diagnostics

Manual smoke tests live in:

```text
tools/diagnostics/
```

They are intentionally excluded from automated test discovery. Many operate on real files or local services; read the script before running it.

### Maintenance

Manual maintenance/audit commands live in:

```text
tools/maintenance/
```

Example dry-run audio audit:

```bash
python tools/maintenance/legacy_audio_audit.py
```

### Backfills

Historical repair/backfill utilities live in:

```text
tools/backfill/
```

These should be treated as one-off administrative tools, not normal application flow.

### Query CLI

Optional command-line query tools live under:

```text
tools/query/
```

The supported end-user query experience is the native Swift app.

## Adding tests

A new automated test should:

- use `unittest` so it participates in the single standard suite;
- avoid external network access;
- mock Ollama/process calls unless an integration test explicitly requires the production path;
- use temporary directories for filesystem mutation;
- never depend on real archived meetings or personal data;
- never perform work merely by being imported.

For summary/memory fixes, favor an integration regression that exercises the actual production composition path rather than only isolated helper functions.

## Repository cleanup policy

Delete dead code only when it is clearly unreferenced/replaced and the current test suite remains green. Git history is the archive; the working tree should describe the current product.

Historical planning documents belong in `docs/internal/`, and retired UI implementations belong in `legacy/` rather than the root application surface.
## Public/private configuration rule

Any feature that uses organization-specific runtime context must provide:

- a public-safe schema/loader and generic example,
- a Git-ignored local override for real values,
- tests proving the application works without the private file, and
- tests validating private overrides when present.

Never commit real staff names, supplier aliases, internal acronyms, project names,
or organization-specific canonical mappings. When the schema changes, update the
public example, loader, tests, and documentation together.

## Public-release privacy validation

Before sharing or exporting the repository, run:

```bash
python tools/release_audit.py
```

Maintain real sensitive names, supplier aliases, internal acronyms, domains, and project terms only in the Git-ignored `release_audit.local.json`, initialized from `release_audit.example.json`. The scanner checks the Git-tracked release surface; ignored private runtime files remain local.

See [Public Release Privacy Guide](PUBLIC_RELEASE.md) for the complete release process.

For a fresh-history-ready export, use `python tools/build_public_release.py` after all tests and the private release audit pass. See [Public Release Privacy Guide](PUBLIC_RELEASE.md).
