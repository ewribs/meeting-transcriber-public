# Changelog

This changelog tracks meaningful product, architecture, workflow, and reliability changes in Meeting Transcriber. It is intentionally curated rather than being a commit-by-commit diary.

Use the `Unreleased` section for user-visible features, significant bug fixes, and architecture/workflow changes that should carry into the next release. Routine refactors, typo fixes, and test-only maintenance usually belong in Git history rather than here.

## Unreleased

### Added
- Added a repeatable public-release export builder that strips private/per-user state, rewrites public-safe bundle identifiers, and requires a clean release audit.

### Added
- Added a tracked-file public-release audit scanner with optional Git-ignored sensitive-literal denylist support.
- Added a Public Release Privacy Guide covering sanitized exports, fresh public history, and manual review requirements.
- Hardware-aware performance profile UX in Preferences, including detected hardware, effective profile resolution (for example, `Auto → High Performance`), context mode, effective context size, and direct-token budget.
- Repository-wide automated regression discovery under `tests/` with a single documented test command.
- Primary project documentation set:
  - `README.md`
  - `docs/INSTALL.md`
  - `docs/USER_GUIDE.md`
  - `docs/ARCHITECTURE.md`
  - `docs/DEVELOPMENT.md`

### Changed
- Removed tracked Xcode per-user state and anonymized remaining legacy/Swift/source examples that identified a developer, coworker, or supplier.
- Externalized organization-specific topic-normalization rules into Git-ignored local business context configuration.
- Externalized local user identity/self-reference aliases into a Git-ignored runtime configuration so real names no longer need to live in committed application source.
- Replaced organization-specific people and supplier examples in production prompt templates with behavior-equivalent generic examples for safer public-release preparation.
- Reorganized automated tests under `tests/` and moved manual smoke/diagnostic scripts under `tools/diagnostics/` so they are no longer executed accidentally by test discovery.
- Moved maintenance, backfill, and query utilities under `tools/`.
- Moved retired Qt/PySide application code under `legacy/qt/`.
- Simplified and clarified Python runtime dependencies, including explicitly declaring the Markdown dependency used by the current backend.
- Clarified the SwiftUI/Python boundary in project documentation: Swift owns the native app experience while Python remains the source of truth for transcription, AI, memory, sessions, persistence, and publishing.

### Fixed
- Stabilized grounded meeting-memory and summary composition so precision-sensitive sections are sourced from structured evidence rather than free-form narrative output.
- Fixed explicit decision recovery for vendor-removal decisions and semantic deduplication of repeated decision fragments.
- Prevented malformed or rhetorical questions from being promoted into authoritative open questions.
- Prevented unsupported vendor-selection language from being promoted into structured decisions/topics.
- Fixed topic-status reconciliation so an approved decision does not incorrectly imply an entire migration or implementation topic is complete.
- Fixed duplicate Topics rendering in the SwiftUI meeting detail view.
- Fixed metadata ordering/recovery so completed transcript/summary artifacts can resume safely without rerunning Whisper or the LLM.
- Fixed narrative consistency so the Executive Summary cannot claim there were no decisions or claim action items existed when authoritative structured sections say otherwise.

## Development Milestones

### 2026-09-27 — Repository, documentation, and performance-profile cleanup

#### Added
- Completed a full repository cleanup pass while preserving meaningful automated regression coverage.
- Established `tests/`, `tools/`, `legacy/`, and `docs/internal/` as the primary homes for automated tests, utilities, retired UI code, and historical planning notes.
- Added the full user/developer documentation set and linked it from the root README.
- Added backend-provided descriptions for performance profiles so Swift can display behavior without duplicating resolution logic.
- Added Preferences display for detected hardware, requested profile, effective profile, context mode, effective context size, and direct-token budget.

#### Changed
- Converted manual `test_*.py` scripts into explicitly named diagnostics outside the automated test suite.
- Consolidated test discovery into:

  ```bash
  python -m unittest discover -s tests -p 'test_*.py' -v
  ```

- Verified the reorganized suite with 286 passing automated tests after the cleanup.

### 2026-09-26 — Grounded meeting memory and summary stabilization

#### Changed
- Made structured meeting memory authoritative for precision-sensitive summary sections such as Decisions, Action Items, Open Questions, and Topics.
- Added deterministic recovery and reconciliation around explicit transcript-supported decisions rather than adding another LLM validation pass.
- Preserved the hardware-aware Direct vs. Chunked execution strategy and the existing Whisper chunking model while tightening post-processing.

#### Fixed
- Recovered explicit decisions that the structured extractor omitted.
- Removed malformed ASR decision fragments and semantic duplicates.
- Rejected synthetic analyst-style questions and malformed/rhetorical transcript questions from authoritative meeting memory.
- Prevented topic summaries from inventing action items when authoritative commitments/follow-ups were empty.
- Prevented unsupported vendor recommendations from becoming authoritative facts.
- Corrected topic status handling for unresolved amendments, migrations, and implementation work.
- Corrected narrative/structured-section contradictions.
- Added production-path regression coverage based on real failure modes uncovered during repeated end-to-end validation.
- Fixed post-summary artifact ordering so metadata is created before structured consumers and refreshed after final artifact generation.
- Added recovery behavior that can reuse completed transcript/summary artifacts instead of retranscribing/re-summarizing after late-stage failures.

### September 2026 — Native SwiftUI application expansion

#### Added
- Native SwiftUI application shell for Meetings, Sessions, Search, Preferences, and Transcribe workflows.
- Native multi-channel recording flow using the established five-channel audio contract.
- Swift meeting browser/detail views backed by Python services.
- Saved Sessions with fixed and dynamic criteria.
- Persisted session conversation history and resume/continue behavior.
- Global search across structured meeting fields and saved sessions.
- Prompt favorites and reusable query recipes.
- Hardware-aware execution profiles and Auto resolution based on detected Apple Silicon hardware/memory.
- Query execution planning with Direct and Chunked modes, token budgeting, context overrides, execution metadata, and calibration telemetry.
- Queue-based transcription workflow and resumable publish/archive behavior.

#### Changed
- Established Python as the backend/source of truth while moving the user experience to SwiftUI.
- Kept model discovery, performance-profile resolution, session/query logic, persistence, and publishing in Python and exposed them through the backend bridge.
- Improved meeting-detail text presentation and split-pane behavior for the native application.

### August 2026 — Archive, metadata, and meeting-index foundation

#### Added
- Meeting metadata and consolidated meeting index generation.
- OneNote-friendly export generation and recovery support.
- Archive/publish lifecycle with verification and retention controls.
- Meeting browsing/indexing foundations that later supported the native application.

---

## v1.2 — 2026-08-06

### Added

#### OneNote Export Workflow
- Added OneNote-friendly HTML export generation.
- Added recovery option to generate OneNote exports from completed meetings.
- Added dedicated `exports/` directory for generated artifacts.
- OneNote export filenames include the meeting run identifier for easy NAS sharing.
- OneNote exports can be regenerated without rerunning Whisper or AI processing.

#### Meeting Metadata Foundation
- Added centralized application metadata configuration.
- Added `APP_NAME` and `APP_VERSION` configuration values.
- Added new `metadata.py` module for generating `meeting_metadata.json`.
- Metadata tracks meeting identity and generated artifacts.
- Recovery workflows automatically refresh metadata after artifact changes.

#### Meeting Index Foundation
- Added `indexer.py` module for generating a consolidated meeting index.
- Added `meeting_index.json` generation from individual `meeting_metadata.json` files.
- Added meeting location references to index entries for future navigation and archive workflows.
- Added isolated index test coverage.

### Changed

#### HTML Generation
- Consolidated HTML generation usage across recovery workflows.
- Updated rebuild workflow to use shared HTML generator functions.

### Developer Experience
- Added reusable metadata test coverage.
- Added developer virtual environment helper script.
- Continued small, feature-focused Git commits.

## v1.1 — 2026-08-03

### Added
- Introduced a dedicated `html_generator.py` module.
- Added reusable `build_transcript_html()` function.
- Added reusable `build_summary_html()` function.
- Added isolated HTML generator test coverage.
- Began the project documentation structure.

### Changed
- Refactored `transcribe.py` to delegate HTML generation to `html_generator.py`.
- Removed approximately 150 lines of embedded HTML/CSS from `transcribe.py`.
- Eliminated duplicated HTML generation logic.
- Transcript HTML generation now uses reusable helper functions.
- Summary HTML generation now uses reusable helper functions.
- Verified that HTML output remained functionally identical after refactoring.
- Added exception handling around AI cleanup and summary generation to allow the pipeline to continue when individual chunks fail.

### Infrastructure
- Initialized Git repository.
- Established first project commit history.
- Tagged initial working baseline as **v1.0**.
- Adopted small, feature-focused Git commits.

## v1.0 — 2026-08-03

### Initial Release

#### Features
- Zoom meeting transcription pipeline.
- Separate transcription of remote and microphone audio.
- Automatic transcript merging.
- Silence removal.
- Adjacent speaker merging.
- AI-powered transcript cleanup.
- Hierarchical AI meeting summarization.
- Markdown transcript generation.
- HTML transcript generation.
- HTML meeting summary generation.
- Chunked processing for long meetings.
- Project preflight validation.

#### Documentation
- Initial README.
