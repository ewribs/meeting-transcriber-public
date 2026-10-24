# Swift App Guide

A tour of the native Meeting Transcriber app: what each part does and how to
do common tasks. For installation see [INSTALL.md](INSTALL.md); for the
design see [ARCHITECTURE.md](ARCHITECTURE.md).

The app has four workspaces, listed in the left-hand sidebar:

- **Transcribe** — record or add audio and watch it process.
- **Meetings** — browse, organize, ask questions about, and compare meetings.
- **Speakers** — name the voices that keep coming back (optional voice recognition).
- **Search** — search across everything.

Preferences (**⌘,**) holds settings, grouped into tabs.

---

## Transcribe

### Record a meeting

1. Make sure a Recordings folder is set in Preferences → Storage.
2. Optionally type a **Meeting name**.
3. Click **Record**. Click **Stop Recording** when finished.
4. The app finalizes the capture and adds it to the **Transcription Queue**.

If the audio input disappears mid-meeting, use **Reconnect Input**.
**Discard…** throws the current recording away after a confirmation.

### Add an existing recording

Use **Add Existing Recording…**. The Recordings folder opens by default, but you can
choose a file anywhere. Recordings are processed one at a time.

### If the app quits during a recording

Audio is written to disk as it is captured. The next time the app starts, any
unfinished recording is finalized automatically and added to the queue. If a
recording cannot be finalized, the app keeps the raw capture and offers
**Reveal Recovery File** so nothing is lost.

---

## Meetings

The Meetings workspace has three parts: a **sidebar** on the left, a **meeting
list** in the middle, and a **detail area** on the right.

### The sidebar

Top rows (each can be hidden in Preferences → Meetings → Sidebar):

- **All Meetings**
- **Recent** — meetings from the last N days (set in Preferences).
- **Unpublished** — processed locally but not yet published to the archive.
- **Not in a Folder** — meetings you have not filed yet.

Below them:

- **Folders** — your own groupings. A meeting can be in more than one folder.
- **Dynamic Sessions** — sessions defined by rules; their members update
  themselves.
- **Fixed Sessions** — sessions with a hand-picked set of meetings.

Click any row to filter the meeting list to it. The count beside each row is
the number of meetings.

**Reordering.** The sort button above Folders sets **A–Z** or **Manual (drag to
reorder)**. In Manual you drag folders and sessions into the order you want.
Dragging an item into place while A–Z is selected switches to Manual and keeps
the current order as the starting point. The setting is also in
Preferences → Meetings → Sidebar.

### The meeting list

- Choose how meetings are **sorted** (Newest First, Oldest First, Title A–Z) with the sort button above the list, or in Preferences.
- Use the **Group by** control above the list: No Grouping, By Month, or By Person.
- Choose **density** (Compact, Normal, Roomy) in Preferences → Meetings.
- Use the search field to filter the list. When a folder or session is
  selected the filter applies inside it.

### The detail area

A control at the top switches between:

- **Meeting** — summary, transcript, topics, decisions, action items, open
  questions, who spoke and processing details for the selected meeting.
- **Ask** — ask questions across the selected meetings or the selected
  session (see below).
- **Changes** — appears only when a session is selected (see below).

### Voices in a meeting

With voice recognition on, the **Who Spoke** section lists the people heard and
how long each spoke. **Voices…** in the meeting header opens a sheet with every
voice in that meeting: listen to short clips, and name a voice you recognize.
Only the voice you choose is named, and your other meetings are re-checked
afterwards. **Change…** next to a name fixes a wrong one and takes back what the
app learned from it. Voices that are really static or silence are shown at the
bottom with a note. See [Speakers](#speakers) below.

### Publish, unpublish and delete

Publishing copies a finished meeting to the archive and verifies it. Deleting
and unpublishing show a plan first. See [File Lifecycle](FILE_LIFECYCLE.md).

---

## Working with folders

| To do this | Do this |
| --- | --- |
| Create a folder | **New Folder…** in the sidebar |
| Put a meeting in a folder | Right-click it → **Add to Folder** |
| Take it out of a folder | Right-click → **Remove from “folder”** (or **Remove from All Folders**) |
| Rename or delete a folder | Right-click the folder (deleting asks for confirmation unless you turned that off) |
| Turn a folder into a session | Right-click the folder → **Make Session from Folder…** |

A session made from a folder is a **Fixed** session containing the folder's
meetings at that moment.

---

## Sessions

A session is a saved set of meetings you can ask questions about, with its
conversation history kept.

### Fixed sessions

You choose the meetings. Create one from a folder, or add meetings to a
session with a meeting's **Add to** menu. A **members** strip in the Ask
view shows which meetings are in the session; click it to see and manage them.

### Dynamic sessions

You write **rules** and the app finds the meetings. Click **+** beside
Dynamic Sessions, or right-click a session → **Edit Rules…**.

Rule types: **Person is**, **Person is any of**, **Title contains**, **Title
does not contain**, **Topic contains**, **Topic does not contain**, plus a
date window.

- **Match** — choose **All rules** (every rule must match) or **Any rule**
  (a meeting matching any one rule is included).
- The **Preview** box shows how many meetings match, and the first few, as you
  edit. A session can't be saved until at least one meeting matches.

Dynamic sessions stay current automatically. When the app opens, and
whenever a meeting is added, published, or deleted, every Dynamic session's
rules are re-run. You can still choose **Refresh** from a session's
right-click menu to force it.

### Quick 1v1 sessions

Right-click a meeting → **Make 1v1 Session With** → choose a person. This
creates a Dynamic session for that person's meetings with "1v1" in the title,
across all history, in one step.

### Asking questions (the Ask view)

Select meetings or a session and use **Ask this Context**. Answers come from
the local model, so a large session can take a while ("Qwen is working…").
Prompt favorites give quick access to questions you reuse; they can be
hidden in Preferences → Meetings.

### Changes

For a selected session, **What changed since last time?** compares the two most
recent meetings and highlights what is new, resolved or different. It is only
as good as the meetings in the session; use **Refresh** on this view to
compare the latest.

---

## Search

Search looks across all indexed meeting and session content.

- **Everything** searches all of it.
- The scope menu narrows the search to one folder or one session.
- Click a result to jump to the meeting or session.

---

## Speakers

The Speakers workspace is for voice recognition (optional; see the
[User Guide](USER_GUIDE.md#voice-recognition-optional)). It lists voices that
keep coming back across meetings but have no name yet, biggest first.

- **Listen** makes three short clips; click one to play or stop it.
- Type a name (or choose from **Known people**) and click **Name Group**, then
  confirm. Every voice in the group is named and the app re-checks your other
  meetings.
- **Hide for Now** moves a group to a collapsed *Hidden* section; **Don't Track**
  moves it to *Not tracked*. **Bring Back** returns it.
- **Name Voices in a Meeting** picks a recent meeting and opens its voices, for
  naming someone who has not appeared in enough meetings to form a group.
- **Refresh** reloads the list.

Listening clips are deleted when you leave the screen or quit the app.

---

## Preferences (⌘,)

Settings are split into four tabs.

**Storage** *(Save / Reload at the bottom)*

- *Folders:* Recordings, Working and Archive folders, and the archive status.
- *Recording Retention:* how long local and archived source audio is kept.
  `0` for archived means keep forever.
- *Backups:* shows the last backup, an optional **second backup folder**
  (for example on a NAS) with **Choose…** and a connection status line, how
  many backups to keep on this Mac (default 20) and in the second folder
  (default 60), and **Back Up Now**. Values are saved with **Save**; Back Up
  Now saves them first. Restoring stays on the command line.

**Local AI** *(Save / Reload at the bottom)*

- *AI Engine:* backend (Auto, Ollama, MLX), the effective backend and model,
  and the Ollama model.
- *Performance:* performance profile and detected hardware.
- *Advanced:* context override. Leave at Profile default for normal use.

**Meetings** *(applies instantly; nothing to save)*

- *Meeting List:* how many days "Recent" covers, sort order, list density.
- *Sidebar:* show or hide Recent, Unpublished and Not in a Folder; sort order
  for folders and sessions.
- *Notices and Confirmations:* notices, confirm before deleting a folder, and
  showing prompt favorites in Ask.

**Voices** *(applies instantly; nothing to save)*

- *Voice Recognition:* a switch to recognize voices after each transcription,
  and a switch to list the people who spoke as the meeting's participants. The
  first switch cannot be turned on until the voice tools are set up and at
  least one person has a voice fingerprint; the tab says what is missing.
- *Unnamed Voices:* how long the fingerprints of voices without a name are
  remembered (1 month, 3 months, 6 months, 1 year, or never delete). Named
  people are not affected.
- *Status:* how many people have a fingerprint and the most recent automatic
  runs. Name voices in the **Speakers** workspace; see the
  [User Guide](USER_GUIDE.md#voice-recognition-optional).

---

## Safety nets

- **State backups.** The app keeps local copies of your folders, saved
  sessions and local-only project files. From the project folder,
  `tools/mt backup` makes one, `tools/mt backup --list` shows them, and
  `tools/mt backup --restore NAME` previews a restore (add `--apply` to do
  it). `tools/mt backup --set-mirror PATH` also copies each backup to another
  folder, such as one on a NAS.
- **Recording recovery.** See above: unfinished recordings are finalized on
  the next launch.
- **Plan before delete.** Destructive meeting operations show what will
  happen first.

## Everything stays local

Whisper and the language model run on your Mac. Meeting data stays in your
configured local and archive folders.
