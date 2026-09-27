# Meeting Transcriber File Lifecycle & Retention

This document describes the current file lifecycle for Meeting Transcriber, including where audio and generated artifacts live, what Publish & Archive does, what is deleted automatically, and the safeguards that protect source recordings.

## Storage locations

Runtime paths can be overridden in **Settings → Preferences**.

- **Source recordings:** `meetings/*.m4a`
- **Local working/output folder:** `output/<timestamp>_<meeting>/`
- **Archive/NAS:** configured archive root, currently `/Volumes/Transcribe`
- **Archived source recording:** `<archive>/<meeting>/source/<original>.m4a`
- **Synology recycle bin:** `/Volumes/Transcribe/#recycle` when enabled on the NAS share

The output and archive locations are configurable. The `meetings/` source-recording folder remains the local intake/source location.

## 1. Intake

An original meeting recording is stored as an M4A in `meetings/`.

Example:

```text
meetings/Rebecca1v1091426.m4a
```

The M4A is the original source recording. Selecting or queueing it in the GUI does not move or delete it.

## 2. Transcription

Transcription creates a timestamped run folder under the configured output directory.

Example:

```text
output/2026-09-14_1054_Rebecca1v1091426/
```

The run contains temporary audio plus the derived meeting artifacts. Typical contents include:

```text
output/<run>/
├── audio/
│   ├── remote.wav
│   └── mic.wav
├── transcript/
├── meeting_transcript.md
├── meeting_transcript_cleaned.md
├── meeting_transcript.html
├── meeting_summary.md
├── meeting_metadata.json
├── meeting_memory.json
└── other generated/export artifacts
```

The WAV files are temporary working audio used for transcription. They remain in the local run while the meeting is **Unpublished**.

A successful transcription creates an Unpublished meeting immediately. Publishing is not required for the meeting to appear in the Meetings browser.

## 3. Publish & Archive

Publish & Archive is available either automatically from the Transcribe queue or manually for an Unpublished meeting in the Meetings tab.

The current publish sequence is:

1. Resolve the original source M4A whose name matches the run-folder suffix.
2. Copy the complete local run folder to the archive/NAS.
3. Create `<archived meeting>/source/` and copy the original M4A into it.
4. Verify that the archived source M4A exists and its file size matches the local source.
5. Copy the OneNote export to the configured import location.
6. Rebuild the archive index.
7. Rebuild the archive dashboard.
8. Remove WAV files from the active archived meeting.
9. Remove WAV files from the local output run.
10. Apply local-source M4A retention.
11. Apply archived-source M4A retention.

If source-M4A archival fails during the archive-copy stage, the partial archive destination is removed rather than leaving a falsely published meeting behind.

## 4. WAV retention

### Published meetings

For a successful publish, temporary WAVs are deleted from both:

- `output/<run>/audio/`
- `<archive>/<meeting>/audio/`

The derived meeting artifacts remain.

### Unpublished meetings

An Unpublished local run may still contain its WAV files because WAV cleanup occurs during successful publishing. Long-lived Unpublished meetings therefore can consume significant local storage and are surfaced by the legacy-audio audit.

### Synology recycle bin

When the NAS share has Synology recycle-bin support enabled, deleting archived WAVs can move those files into:

```text
/Volumes/Transcribe/#recycle/
```

Those files are no longer part of the active Meeting Transcriber archive. Recycle-bin retention and purging are managed by Synology, not by Meeting Transcriber. The current NAS policy is configured to purge the recycle bin daily.

The audio audit reports recycle-bin WAVs separately for visibility and excludes them from app-managed reclaimable-storage totals.

## 5. Local source M4A retention

The local source M4A retention period is configurable in Preferences. The current default is **30 days**.

Retention is conservative. An old local M4A is eligible for deletion only when all of the following are true:

1. The source M4A is older than the configured local retention period.
2. Exactly one matching archived meeting exists.
3. The archive contains the required derived artifacts:
   - `meeting_summary.md`
   - `meeting_transcript_cleaned.md`
   - `meeting_metadata.json`
   - `meeting_memory.json`
4. The archived source M4A exists under `<archive>/<meeting>/source/`.
5. The archived source M4A file size matches the local source M4A.

If any verification fails, the local M4A is **skipped**, not deleted.

The local-retention scan runs after a successful GUI Publish & Archive operation and examines all aged source M4As, not only the meeting just published.

## 6. Archived source M4A retention

The archived source M4A retention period is separately configurable in Preferences. The current default is **365 days**.

- A value greater than zero means an archived source M4A can be removed after that many days when the archived meeting still has the required derived artifacts.
- A value of **0 means Forever**.

Deleting an archived source M4A does **not** delete the meeting's transcript, summary, metadata, memory, or other retained derived artifacts.

The archived-source retention scan runs after a successful GUI Publish & Archive operation.

## 7. Failure and safety behavior

The retention model favors keeping audio over deleting it when state is ambiguous.

Examples of conditions that block local-source deletion:

- no matching archive exists;
- more than one archive appears to match the source;
- required archive artifacts are missing;
- archived source M4A is missing;
- archived source M4A size does not match the local source.

A publish failure does not intentionally cause retranscription. The completed local run remains available as an Unpublished meeting and can be published again.

Because WAV removal happens late in the publish sequence, a publish that fails after archive creation but before WAV cleanup can leave WAVs in an active local or archive folder. The legacy-audio audit is designed to surface these exceptions.

## 8. Legacy Audio Storage Audit

Run:

```bash
python tools/maintenance/legacy_audio_audit.py
```

The audit is **dry-run only** and does not modify files. It classifies:

- WAVs under active local meeting runs;
- Development / Pilot WAVs;
- WAVs still present in the active archive;
- Synology recycle-bin WAVs, informational only;
- local M4As past retention that are safe to remove;
- local M4As past retention that are blocked, including the reason;
- archived source M4As past retention;
- archived source M4As blocked from removal.

The **App-managed reclaimable audio** total excludes Synology `#recycle` and Development / Pilot WAVs.

## 9. Development / Pilot files

Files beneath `output/Pilot Files/` are classified separately from normal meeting runs. They are not treated as current meeting lifecycle artifacts and are excluded from app-managed reclaimable-storage totals.

These files should be reviewed and removed manually when no longer needed for development/testing.

## Lifecycle summary

```text
Original M4A
    │
    ├── meetings/<source>.m4a
    │
    ▼
Transcription
    │
    ├── output/<meeting>/audio/*.wav       temporary
    ├── output/<meeting>/transcripts       retained artifacts
    ├── output/<meeting>/summary           retained artifacts
    └── meeting becomes Unpublished
    │
    ▼
Publish & Archive
    │
    ├── copy run to archive
    ├── copy source M4A to archive/source/
    ├── verify archived source by file size
    ├── rebuild exports/index/dashboard
    ├── delete active archive WAVs
    └── delete local output WAVs
    │
    ├── local source M4A
    │      └── eligible after configured local retention
    │          only with verified complete archive
    │
    └── archived source M4A
           └── eligible after configured archive retention
               0 = Forever
```

## Operational ownership

- **Meeting Transcriber:** active meeting files, verified source archival, WAV cleanup, source-M4A retention, audit/reporting.
- **Synology:** NAS recycle-bin retention and purge schedule.
- **User/Development:** manual cleanup of intentionally retained development and Pilot Files.
