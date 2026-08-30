# notes-backup

**Time Machine for Apple Notes.** Every hour, your notes are saved to a local
git repo so you can see what any note looked like yesterday, last week, or last
month — and get it back.

## Why

Apple Notes has no version history. Delete a note and you get ~30 days of
"Recently Deleted." But *mangle* a note — paste over it, lose half of it to a
bad sync, let a toddler "edit" it — and there's no undo. Your note is just
gone, and it looks like it was always that way.

This tool fixes that. A quiet background job exports every note to a plain
Markdown file and commits it to git, so every note gets a diffable history and
a one-command rollback. Your iPhone needs nothing: if your notes sync via
iCloud, they're already in the Mac's local Notes database, and that's what gets
backed up.

## What it does

Every hour (or however often you like), it:

1. **Exports every note to Markdown** — text, checklists, and attachments
   (images, PDFs, …), in a folder tree that mirrors your accounts and folders.
2. **Commits to git** — only when something actually changed, so the history
   stays meaningful.
3. **Snapshots the raw Notes database** too, as a perfect-fidelity fallback
   for anything Markdown can't capture. These are gzipped and thinned out on a
   schedule (6-hourly for 2 days, daily for a week, then monthly forever).

Everything lands in `~/NotesBackup`:

```
~/NotesBackup/
├── notes/<Account>/<Folder>/<Title>.<uuid>.md   # your notes, in git
├── media/<note-uuid>/<attachment files>         # attachments, in git
└── snapshots/db/NoteStore-<timestamp>.sqlite.gz # raw DB snapshots
```

Nothing leaves your Mac. It's a local folder and a local git repo.

---

## Install (the easy way)

Installing involves a Python environment, a launchd job, and granting
**Full Disk Access** to exactly the right binary — all doable, but fiddly.
Instead, let [Claude Code](https://claude.com/claude-code) or
[Codex](https://openai.com/codex) do it.

Open Claude Code / Codex and paste this in as your message:

```
Can we install this Apple Notes backup tool: https://github.com/texjer/notes-backup
```

The agent will clone the repo, run the installer, and walk you through the one
step it can't do for you: granting Full Disk Access to the tool's Python
binary in System Settings (macOS requires this to read the Notes database).
After that, backups run hourly and at login, automatically.

## Install (manual)

If you'd rather do it yourself:

```sh
git clone https://github.com/texjer/notes-backup.git
cd notes-backup
./install.sh              # or: ./install.sh /path/to/backup/dir
```

Then grant **Full Disk Access** to `.venv/bin/python3` — the installer opens
the right System Settings pane and prints the exact path to add. This is
scoped to the project's own private Python binary, not your whole shell.

That's it. The job runs hourly (configurable) and at login.

---

## Getting a note back

Everything is plain git, so any git tool works. From the terminal:

```sh
cd ~/NotesBackup

# What changed recently?
git log --oneline

# History of one note
git log --follow --oneline -- "notes/iCloud/Recipes/Chili.*.md"

# What did it say yesterday?
git show 'main@{yesterday}' -- "notes/iCloud/Recipes/Chili.*.md"

# Bring back an old version (then paste it into Notes)
git checkout <commit> -- "notes/iCloud/Recipes/Chili.*.md"
```

Or skip the commands entirely and tell your agent: *"Show me what my Chili
recipe note looked like last Tuesday."*

For anything the Markdown export doesn't capture, `gunzip` a raw snapshot from
`snapshots/db/` and open it with a tool like
[apple_cloud_notes_parser](https://github.com/threeplanetssoftware/apple_cloud_notes_parser).

---

## Configuration

Settings live in `~/.config/notes-backup/config.json`:

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

- **`backup_dir`** — where everything goes.
- **`db_snapshot_tiers`** — how long to keep raw DB snapshots, finest tier
  first. A snapshot falls into the first tier whose `for_days` covers its age
  (`null` = forever), and one snapshot per `every_hours` window is kept.
- **`commit_media`** — set to `false` to keep attachments out of git if disk
  space matters (they're stored twice: working tree + git object).

Change the interval at install time: `NOTES_BACKUP_INTERVAL=1800 ./install.sh`
(seconds; default 3600). Re-running `install.sh` is always safe.

Run a backup by hand: `.venv/bin/python3 notes_backup.py`
(your terminal app needs Full Disk Access too).
Log: `~/Library/Logs/notes-backup.log`.

**Disk usage**: note text is tiny (1,400 notes ≈ 6 MB) and git stores hourly
changes as small deltas. Attachments and raw DB snapshots (~20 MB gzipped
each, ~20 kept at steady state) are what take space.

---

## Good to know

- **Password-protected notes** can't be exported — a placeholder file records
  that they exist. The raw DB snapshots still hold their encrypted data.
- **Formatting**: the Markdown export captures text, checklists, and
  attachments; complex rich-text details may be simplified. The raw snapshots
  are the perfect-fidelity layer.
- **macOS only** — it reads the Mac's local Notes database. iOS-only notes are
  covered as long as they sync via iCloud.
- **The backup lives on your Mac's disk.** For real disaster protection, put
  `~/NotesBackup` somewhere that's itself backed up, or add a git remote.
  **Your notes likely contain sensitive stuff** — if you push anywhere, make it
  a private repo you trust.

## Uninstall

```sh
./uninstall.sh   # removes the launchd job; never touches your backups
```

(Or just tell your agent: *"Uninstall notes-backup."*)

## Credits

Built on [apple-notes-parser](https://github.com/RhetTbull/apple-notes-parser)
by Rhet Turnbull, which decodes Apple's protobuf note format.

[MIT](LICENSE)
