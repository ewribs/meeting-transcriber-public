# Tools

Manual utilities are separated from automated tests so test discovery stays side-effect free.

- `backfill/` — one-off historical artifact/data backfills.
- `diagnostics/` — manual smoke tests and local diagnostics.
- `maintenance/` — audits and maintenance helpers.
- `query/` — optional command-line query/session tools.

These tools may operate on real local or archived meeting data. Review a script before running it.

## setup/

Transparent macOS installation and validation helpers. `bootstrap_macos.sh` is
dry-run/check capable, `configure_install.py` writes local Application Support
configuration, `validate_install.py` performs read-only diagnostics, and
`install_from_github.sh` can clone/update the public repository before setup.
See `docs/SETUP_AND_SECURITY.md` before use.

## Native app install

`install_local_app.sh` builds a Release copy of the Swift app, records the current
repository path for the Python backend, installs the app into `~/Applications` by
default, and launches it for normal Dock use. It does not package private meeting
data or local identity files.

### Legacy audio archive repair

`maintenance/repair_legacy_audio_archives.py` backfills original source M4As
into older complete archives that predate source-audio archival. It is a dry run
by default. Use `--apply` only after reviewing the plan. The tool refuses
no-match, multi-match, incomplete, or conflicting archive cases and does not
delete local recordings.
