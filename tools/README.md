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
