# Notes Backup for iOS Notes.app

**Versioned, rollback-able backups of Apple Notes on macOS.**

If you accidentally delete a Note from Apple Notes, its not a big deal, you can just recover it. But if you 

Apple Notes has no version history. If you accidentally delete a note you have
~30 days of "Recently Deleted" — but if you mangle a note's *contents* (paste
over it, a bad sync, an overzealous edit), nothing saves you. This tool fixes
that: an hourly background job exports every note to Markdown and commits it
to a local git repo, so every note gets a diffable history and one-command
rollback. Think Time Machine, but per-note.

Your iPhone needs nothing: if your notes sync via iCloud, the Mac's local
Notes database contains all of them, and that's what gets backed up.

## What each backup run does

1. **Snapshots the raw database** (`NoteStore.sqlite`) using SQLite's online
   backup API — a perfect-fidelity fallback. Gzipped and thinned on a tiered
   schedule: every 6 hours for 2 days, daily for a week, then monthly forever.
2. **Exports every note to Markdown** (with YAML frontmatter: folder, tags,
   dates, pinned) plus its attachments (images, PDFs, …), mirroring your
   account/folder structure.
3. **Commits to git** — only when something actually changed.

Backup layout (default `~/NotesBackup`):

```
~/NotesBackup/
├── notes/<Account>/<Folder>/<Title>.<uuid>.md   # committed to git
├── media/<note-uuid>/<attachment files>         # committed to git
└── snapshots/db/NoteStore-<timestamp>.sqlite.gz # tiered retention, not in git
```

**Disk usage**: your notes' text is tiny (1,400 notes ≈ 6 MB) and git stores
hourly changes as small deltas. What takes space is attachments (stored twice:
working tree + git object) and the raw DB snapshots (the Notes DB is mostly
Core Data sync history — ~20 MB gzipped per snapshot; the default tiers hold
~20 of them at steady state, growing by one per month). Tune
`db_snapshot_tiers` or set `commit_media` to `false` if that matters to you.

## Install

```sh
git clone <this repo> && cd notes-backup
./install.sh              # or: ./install.sh /path/to/backup/dir
```

Then grant **Full Disk Access** to `.venv/bin/python3` (the installer opens
the right System Settings pane and prints the exact path). macOS protects the
Notes database, so this one manual step is unavoidable — it's scoped to this
project's private Python binary, not your whole shell.

That's it. The job runs hourly (configurable) and at login.

## Getting a note back

```sh
cd ~/NotesBackup

# What happened recently?
git log --oneline

# History of one note
git log --follow --oneline -- "notes/iCloud/Recipes/Chili.*.md"

# What did it say yesterday?
git show 'main@{yesterday}' -- "notes/iCloud/Recipes/Chili.*.md"

# Restore a deleted/mangled note's file (then paste it back into Notes)
git checkout <commit> -- "notes/iCloud/Recipes/Chili.*.md"
```

For anything the Markdown export doesn't capture, `gunzip` a raw snapshot from
`snapshots/db/` and open it with a tool like
[apple_cloud_notes_parser](https://github.com/threeplanetssoftware/apple_cloud_notes_parser).

## Configuration

`~/.config/notes-backup/config.json`:

```json
{
  "backup_dir": "~/NotesBackup",
  "db_snapshot_tiers": [
    {"every_hours": 6,   "for_days": 2},
    {"every_hours": 24,  "for_days": 7},
    {"every_hours": 720, "for_days": null}
  ],
  "commit_media": true
}
```

`db_snapshot_tiers` is finest-first: a snapshot falls into the first tier
whose `for_days` covers its age (`null` = forever), and within a tier one
snapshot per `every_hours` window is kept. Snapshots older than the last
tier's `for_days` are deleted, so ending with `null` keeps a thin tail forever.

Set the interval at install time: `NOTES_BACKUP_INTERVAL=1800 ./install.sh`
(seconds; default 3600). Re-run `install.sh` any time — it's idempotent.

Run a backup by hand: `.venv/bin/python3 notes_backup.py`
(your terminal app needs Full Disk Access too).
Log: `~/Library/Logs/notes-backup.log`.

## Caveats

- **Password-protected notes** can't be exported (a placeholder file records
  that they exist). The raw DB snapshots still contain their encrypted data.
- **Formatting fidelity**: the Markdown export captures text, checklists, and
  attachments, but complex rich-text details may be simplified. The raw
  snapshots are the perfect-fidelity layer.
- **macOS only** — it reads the local Notes database. iOS-only notes are
  covered as long as they sync to the Mac via iCloud.
- The git repo lives on the same disk as your Mac. For real disaster
  protection, add a remote (`git remote add …`) or put the backup dir
  somewhere that's itself backed up. **Your notes likely contain sensitive
  data** (keys, addresses, personal info) — if you push anywhere, make it a
  private repo you trust.

## Uninstall

```sh
./uninstall.sh   # removes the launchd job; never touches your backups
```

## Credits

Built on [apple-notes-parser](https://github.com/RhetTbull/apple-notes-parser)
by Rhet Turnbull, which handles decoding Apple's protobuf note format.

MIT license.
