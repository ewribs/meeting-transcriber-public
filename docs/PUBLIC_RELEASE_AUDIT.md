# Public Release Audit — Current Committed Tree

This audit was performed against a Git archive of the committed repository after runtime identity, business-context, prompt, and test-fixture sanitization. The archive intentionally excluded ignored local data and therefore represents the committed surface that could become public.

## Executive summary

The committed tree is substantially cleaner than the earlier development repository. No tracked recordings, transcripts, meeting artifacts, private local configuration files, email addresses, or absolute `/Users/<name>/...` paths were found in the supplied snapshot.

This pass found and corrected four remaining categories of committed identity/business leakage:

1. retired Qt UI examples containing a real coworker name and a real supplier name;
2. production-source comments containing real meeting-participant names from historical examples;
3. Swift/Xcode file headers containing a developer's full name;
4. tracked Xcode `xcuserdata`, which is per-user IDE state and should never be part of a public repository.

A permanent `tools/release_audit.py` guardrail is added by this change.

## Findings corrected in this pass

### Legacy Qt examples — corrected

**File:** `legacy/qt/gui.py`

The retired Qt UI still contained a real-person example for a saved 1:1 session and a real supplier example in topic/title helper text. These values do not participate in the supported Swift application, so they were replaced with generic examples without changing behavior.

**Classification:** Documentation/example — replace.

### Production-source comments — corrected

**File:** `ai.py`

Historical comments around participant-candidate detection and direct-address scoring contained real meeting-participant names. The regular expressions and scoring logic were already generic; only the explanatory examples were identifying. They were replaced with generic names while leaving executable logic untouched.

**Classification:** Documentation/example embedded in source — replace.

### Query comment — corrected

**File:** `query/changes.py`

A comment describing topic-identity reconciliation still referenced a real supplier. It was replaced with a generic endpoint-platform example. No executable behavior changed.

**Classification:** Documentation/example embedded in source — replace.

### Swift personal file headers — corrected

**Files:**

- `swift/Meeting Transcriber/Meeting Transcriber/Meeting_TranscriberApp.swift`
- `swift/Meeting Transcriber/Meeting TranscriberTests/Meeting_TranscriberTests.swift`
- `swift/Meeting Transcriber/Meeting TranscriberUITests/Meeting_TranscriberUITests.swift`

Xcode-generated `Created by <person>` comments were changed to project-generic headers.

**Classification:** Personal metadata — replace.

### Xcode per-user state — remove from tracking

**Path:** `swift/Meeting Transcriber/Meeting Transcriber.xcodeproj/xcuserdata/`

The committed snapshot contained an Xcode user-data path carrying a local account identifier. `.gitignore` already excludes `xcuserdata/`, so the correct remediation is to delete the tracked copy and leave it ignored going forward.

**Classification:** Private developer state — remove.

## Intentional remaining manual-review item

### Bundle identifiers

The private development checkout may use a developer-specific bundle-ID namespace so macOS permissions, preferences, signing, and local app identity remain stable. The release-audit scanner reports those identifiers as warnings in the private repo.

The public-release export process does **not** publish those identifiers. `tools/build_public_release.py` rewrites the exported Xcode project to a public-safe namespace (default: `org.example.meetingtranscriber`) and then runs the release audit with warnings treated as failures. A completed public export therefore must report **0 errors and 0 warnings**.

If a future maintainer owns an appropriate domain/namespace, pass a different public bundle prefix explicitly when building the export. Changing the private development bundle IDs is not required.
## Binary/assets review

The tracked app icon assets were visually inspected. They contain a generic waveform/speech-bubble application mark and no visible names, employer branding, meeting content, or supplier branding.

No tracked M4A, WAV, MP3, MP4, MOV, AIFF, or CAF media artifacts were present in the supplied Git archive.

## Private runtime data status

The committed tree now uses the intended public/private pattern:

- `identity.example.json` is public; `identity.local.json` is ignored/private.
- `business_context.example.json` is public; `business_context.local.json` is ignored/private.
- `known_people.example.json` is public; real known-people files are ignored/private.
- `release_audit.example.json` is public; `release_audit.local.json` is ignored/private.

The private release-audit file should contain real employee names, supplier names/aliases, employer/internal domains, acronyms, project names, and other terms that must never appear in the public tree.

## Legacy directory decision

`legacy/qt/` is retained in the private development repository for historical reference. It is not used by the supported Swift runtime or automated test suite. This pass sanitizes its remaining known identifying examples so keeping it tracked no longer creates the known name/supplier leak.

For a minimal public repository, omitting `legacy/` entirely is still reasonable because it is retired implementation history rather than supported product code.

## Automated audit added

`tools/release_audit.py` scans the Git-tracked release surface and reports:

- tracked private local configuration;
- tracked audio/video artifacts;
- tracked `xcuserdata` / `.xcuserstate`;
- email addresses;
- absolute macOS user paths;
- personal `Created by` headers;
- developer-specific bundle identifiers as manual-review warnings in the private development checkout;
- any private sensitive literal listed in `release_audit.local.json`.

Run:

```bash
python tools/release_audit.py
```

For a final public-release gate, also run:

```bash
python tools/release_audit.py --strict-warnings
```

`--strict-warnings` is appropriate for public exports after the bundle IDs have been rewritten by the release builder.

## Validation performed

- New release-audit tests: 6 passing.
- Full Python regression suite in the audit environment: 307 passing.
- Private development checkout after this cleanup: 0 errors, 6 bundle-identifier warnings.
- Public-release export after bundle-ID rewrite: 0 errors, 0 warnings.

The audit environment does not have the project's real Markdown package installed, so the full suite was executed with a temporary test-only `markdown.markdown()` stub solely to satisfy import-time dependency loading. No stub is included in the patch; the developer environment should run against the real dependency declared in `requirements.txt`.

## Public repository recommendation

Do not change the existing private repository to public visibility. Even after the current tree is sanitized, earlier Git history can retain old identities, work examples, supplier names, and meeting-related strings.

Create any future public repository from a freshly audited sanitized export with new Git history and a deliberate public Git author identity.
