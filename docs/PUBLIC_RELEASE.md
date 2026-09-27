# Public Release Privacy Guide

Meeting Transcriber is developed against real meeting workflows, but the committed repository must remain public-safe. Private runtime context and employer-specific vocabulary belong only in Git-ignored local configuration.

## Public/private boundary

The committed repository may contain:

- application source code;
- generic prompt examples and generic test fixtures;
- public-safe example configuration;
- documentation that does not identify a real employer, coworker, supplier relationship, project, meeting, or internal acronym.

The committed repository must not contain:

- `identity.local.json`;
- `business_context.local.json`;
- `known_people.json` or `known_people.local.json`;
- `release_audit.local.json`;
- recordings, transcripts, generated meeting artifacts, or archived meeting content;
- real staff/coworker names used as fixtures or examples;
- organization-specific supplier aliases, internal acronyms, project/deal names, or meeting titles;
- email addresses, private domains, hostnames, or absolute `/Users/<name>/...` paths;
- IDE/Xcode per-user state such as `xcuserdata/`.

## Release audit

Run the automated audit from the repository root:

```bash
python tools/release_audit.py
```

The scanner inspects Git-tracked files rather than the entire working directory. This allows private local configuration to remain installed without being mistaken for release content.

The scanner always checks for:

- private local configuration files accidentally tracked by Git;
- audio/video artifacts;
- tracked Xcode user state;
- email addresses;
- absolute macOS user paths;
- personal `Created by` source headers;
- bundle identifiers that should receive manual release review.

## Private sensitive-literal denylist

Generic automated patterns cannot know every real coworker, supplier, internal acronym, or project name. Maintain those private terms locally in:

```text
release_audit.local.json
```

Start from:

```bash
cp release_audit.example.json release_audit.local.json
```

Populate `sensitive_literals` with any names, supplier aliases, internal domains, acronyms, project names, or other terms that must never appear in a public release. Do not commit this file.

Example shape:

```json
{
  "sensitive_literals": [
    "Example Employee Name",
    "Example Supplier Name",
    "example.internal"
  ],
  "allowed_bundle_prefixes": [
    "com.example."
  ]
}
```

The real local file should contain the private terms relevant to the developer's environment.

## Manual review still required

The audit is a guardrail, not a substitute for human review. Before publishing, manually review:

- README and documentation examples;
- prompt templates and comments;
- test fixtures;
- diagnostic/backfill scripts;
- screenshots, images, PDFs, and other binary assets;
- app identifiers and signing metadata;
- filenames and sample artifacts;
- changelog/release notes.

`legacy/` is retained for historical reference and is not part of the supported runtime. It still belongs to the tracked release surface, so examples inside it must also remain generic unless the directory is intentionally omitted from a future public export.

## Do not expose the private Git history

Sanitizing the current working tree does not erase sensitive strings from old commits, branches, tags, or pull-request metadata. If Meeting Transcriber is published publicly, create a new public repository from a sanitized committed tree with fresh history rather than changing the existing private repository's visibility.

A safe release sequence is:

1. Ensure the private development repository is clean and all tests pass.
2. Run `python tools/release_audit.py` with the private local denylist installed.
3. Resolve all errors and review all warnings.
4. Produce a Git archive or sanitized export of the current committed tree.
5. Inspect that export separately.
6. Initialize a new public repository from the sanitized export.
7. Use a deliberate public Git author identity for the new repository.

## Repeatable public export

The repository includes a release builder that archives only the current Git `HEAD`, strips private/per-user state, rewrites Xcode bundle identifiers to a public-safe namespace, and requires a warning-free release audit before writing the ZIP.

```bash
python tools/build_public_release.py \
  --output ~/Desktop/meeting-transcriber-public.zip \
  --bundle-prefix org.example.meetingtranscriber
```

Run it only from a clean private development checkout after the full test suite and private denylist audit pass. The generated ZIP contains no Git history; initialize a brand-new public repository from the extracted export.
