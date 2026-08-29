#!/usr/bin/env python3
"""notes-backup: versioned, rollback-able backups of Apple Notes.

Each run:
  1. Snapshots the live NoteStore.sqlite (SQLite online backup API) into
     <backup_dir>/snapshots/db/ and rotates old snapshots.
  2. Exports every note to a Markdown file (plus attachments) under
     <backup_dir>/notes/ and <backup_dir>/media/, mirroring your folder tree.
  3. Commits the result to a git repo in <backup_dir>, giving every note a
     diffable history and one-command rollback.

Requires Full Disk Access for the process running it (see README).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

NOTES_CONTAINER = Path.home() / "Library/Group Containers/group.com.apple.notes"
LIVE_DB = NOTES_CONTAINER / "NoteStore.sqlite"
DEFAULT_CONFIG_PATH = Path.home() / ".config/notes-backup/config.json"

DEFAULT_CONFIG = {
    "backup_dir": "~/NotesBackup",
    # Raw-DB snapshot retention, finest tier first. Within each tier, one
    # snapshot per `every_hours` is kept for snapshots up to `for_days` old
    # (null = forever). Defaults: 6-hourly for 2 days, daily for a week,
    # then one every ~30 days indefinitely.
    "db_snapshot_tiers": [
        {"every_hours": 6, "for_days": 2},
        {"every_hours": 24, "for_days": 7},
        {"every_hours": 720, "for_days": None},
    ],
    "commit_media": True,
}

SNAPSHOT_NAME_FORMAT = "NoteStore-%Y%m%d-%H%M%S.sqlite.gz"

GITIGNORE = "snapshots/\n.DS_Store\n"

FDA_HELP = """\
ERROR: Cannot read the Apple Notes database (macOS blocked access).

The process running this script needs Full Disk Access:
  System Settings > Privacy & Security > Full Disk Access
  - For manual runs: add your terminal app (e.g. iTerm/Terminal).
  - For the scheduled launchd job: add this project's Python binary:
      {python_bin}

Open the settings pane with:
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
"""


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_config(path: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    cfg["backup_dir"] = Path(os.path.expanduser(cfg["backup_dir"]))
    return cfg


def check_db_access() -> None:
    try:
        with open(LIVE_DB, "rb") as f:
            f.read(16)
    except (PermissionError, OSError) as e:
        sys.stderr.write(FDA_HELP.format(python_bin=sys.executable))
        sys.stderr.write(f"\nUnderlying error: {e}\n")
        sys.exit(2)


def copy_live_db(dest: Path) -> None:
    """Copy the live database with SQLite's online backup API (WAL-safe)."""
    src = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")
    finally:
        src.close()
        dst.close()
    for sidecar in (dest.with_name(dest.name + "-wal"), dest.with_name(dest.name + "-shm")):
        sidecar.unlink(missing_ok=True)


def snapshot_timestamp(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.name, SNAPSHOT_NAME_FORMAT)
    except ValueError:
        return None


def prune_snapshots(snapshots: list[Path], tiers: list[dict], now: datetime) -> list[Path]:
    """Thin snapshots to the tiered schedule; returns the survivors.

    Each snapshot falls into the first tier whose `for_days` covers its age,
    and within a tier only the oldest snapshot per `every_hours` window is
    kept — so a snapshot's fate is stable as it ages from tier to tier.
    """
    keep: dict[tuple[int, int], Path] = {}
    for snap in sorted(snapshots):  # oldest first, so the first in a window wins
        ts = snapshot_timestamp(snap)
        if ts is None:
            continue
        age_days = (now - ts).total_seconds() / 86400
        for i, tier in enumerate(tiers):
            limit = tier.get("for_days")
            if limit is None or age_days <= limit:
                window = int(ts.timestamp() // (tier["every_hours"] * 3600))
                keep.setdefault((i, window), snap)
                break
        # Older than every tier's limit: dropped.
    survivors = set(keep.values())
    for snap in snapshots:
        if snap not in survivors:
            snap.unlink()
    return sorted(survivors)


def snapshot_db(backup_dir: Path, working_db: Path, tiers: list[dict]) -> Path | None:
    """Keep gzipped raw-DB snapshots on the tiered schedule in `tiers`.

    The DB is mostly Core Data change-tracking history, so it's large and
    compresses poorly; git carries the hourly text history, these are the
    perfect-fidelity fallback.
    """
    snap_dir = backup_dir / "snapshots" / "db"
    snap_dir.mkdir(parents=True, exist_ok=True)

    for stale in snap_dir.glob("NoteStore-*.sqlite-*"):
        stale.unlink()
    for raw in snap_dir.glob("NoteStore-*.sqlite"):  # pre-gzip snapshots from older versions
        gzip_file(raw)

    now = datetime.now()
    snapshots = prune_snapshots(list(snap_dir.glob("NoteStore-*.sqlite.gz")), tiers, now)
    if snapshots:
        newest = snapshot_timestamp(snapshots[-1])
        if newest and (now - newest).total_seconds() < tiers[0]["every_hours"] * 3600:
            return None

    dest = snap_dir / now.strftime(SNAPSHOT_NAME_FORMAT)
    gzip_file(working_db, dest, delete_source=False)
    return dest


def gzip_file(path: Path, dest: Path | None = None, delete_source: bool = True) -> Path:
    dest = dest or path.with_name(path.name + ".gz")
    with open(path, "rb") as f_in, gzip.open(dest, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    if delete_source:
        path.unlink()
    return dest


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text or "untitled")
    text = re.sub(r"[/\\:\x00-\x1f]", "-", text).strip().strip(".")
    text = re.sub(r"\s+", " ", text)
    return text[:max_len].strip() or "untitled"


def safe_rel_folder(note) -> Path:
    parts = [slugify(p) for p in note.get_folder_path().split("/") if p]
    return Path(slugify(note.account.name)).joinpath(*parts)


def yaml_escape(value) -> str:
    if value is None:
        return '""'
    s = str(value)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_note_md(note, attachment_paths: list[Path], backup_dir: Path) -> str:
    lines = ["---"]
    lines.append(f"title: {yaml_escape(note.title)}")
    lines.append(f"uuid: {yaml_escape(note.uuid)}")
    lines.append(f"folder: {yaml_escape(note.account.name + '/' + note.get_folder_path())}")
    lines.append(f"created: {yaml_escape(note.creation_date)}")
    lines.append(f"modified: {yaml_escape(note.modification_date)}")
    if note.tags:
        lines.append("tags: [" + ", ".join(yaml_escape(t) for t in sorted(note.tags)) + "]")
    if note.is_pinned:
        lines.append("pinned: true")
    if note.is_password_protected:
        lines.append("password_protected: true")
    lines.append("---")
    lines.append("")
    if note.is_password_protected and not note.content:
        lines.append("*(This note is password-protected; its content cannot be backed up.)*")
    else:
        lines.append(note.content or "")
    if attachment_paths:
        lines.append("")
        lines.append("## Attachments")
        lines.append("")
        for p in attachment_paths:
            rel = os.path.relpath(p, backup_dir / "notes")
            lines.append(f"- [{p.name}](../{rel})")
    lines.append("")
    return "\n".join(lines)


def write_if_changed(path: Path, content: str) -> bool:
    data = content.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def build_media_map(snapshot: Path) -> dict[str, Path]:
    """Map attachment UUID -> on-disk media file.

    Media files live at Accounts/<acct>/Media/<media-uuid>/[<generation>/]<name>,
    where <media-uuid> comes from the attachment's ZMEDIA row — not the
    attachment's own UUID, which is what apple-notes-parser searches by.
    """
    media_map: dict[str, Path] = {}
    try:
        conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT a.ZIDENTIFIER, m.ZIDENTIFIER, m.ZFILENAME "
            "FROM ZICCLOUDSYNCINGOBJECT a "
            "JOIN ZICCLOUDSYNCINGOBJECT m ON a.ZMEDIA = m.Z_PK "
            "WHERE a.ZIDENTIFIER IS NOT NULL AND m.ZIDENTIFIER IS NOT NULL"
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        log(f"WARNING: media-map query failed ({e}); "
            "falling back to library resolution only")
        return media_map

    accounts_dir = NOTES_CONTAINER / "Accounts"
    account_folders = [d for d in accounts_dir.iterdir() if d.is_dir()]
    for att_uuid, media_uuid, filename in rows:
        for acct in account_folders:
            media_dir = acct / "Media" / media_uuid
            if not media_dir.is_dir():
                continue
            candidates = [p for p in media_dir.rglob("*")
                          if p.is_file() and not p.name.startswith(".")]
            if not candidates:
                continue
            exact = [p for p in candidates if p.name == filename]
            # Multiple generations of a file: take the most recent.
            best = max(exact or candidates, key=lambda p: p.stat().st_mtime)
            media_map[att_uuid] = best
            break
    return media_map


def export_notes(snapshot: Path, backup_dir: Path, commit_media: bool) -> dict:
    from apple_notes_parser import AppleNotesParser

    parser = AppleNotesParser(str(snapshot))
    parser.load_data()
    notes = sorted(parser.notes, key=lambda n: (n.account.name, n.get_folder_path(), n.id))

    media_map = build_media_map(snapshot) if commit_media else {}
    notes_root = backup_dir / "notes"
    media_root = backup_dir / "media"
    expected: set[Path] = set()
    stats = {"notes": len(notes), "attachments": 0, "attachment_failures": 0, "changed": 0}

    for note in notes:
        note_key = note.uuid or f"note-{note.id}"
        attachment_paths: list[Path] = []
        if commit_media:
            for att in note.attachments:
                fname = att.get_suggested_filename()
                dest = media_root / note_key / f"{att.id}-{slugify(fname, 80)}"
                expected.add(dest)
                attachment_paths.append(dest)
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    ok = False
                    source = media_map.get(att.uuid) if att.uuid else None
                    if source:
                        try:
                            shutil.copy2(source, dest)
                            ok = True
                        except OSError:
                            ok = False
                    if not ok:
                        try:
                            ok = att.save_attachment(dest, notes_container_path=NOTES_CONTAINER)
                        except Exception:
                            ok = False
                    if ok:
                        stats["attachments"] += 1
                    else:
                        stats["attachment_failures"] += 1
                        attachment_paths.remove(dest)
                        expected.discard(dest)
                else:
                    stats["attachments"] += 1

        md_path = notes_root / safe_rel_folder(note) / f"{slugify(note.title)}.{note_key}.md"
        expected.add(md_path)
        if write_if_changed(md_path, render_note_md(note, attachment_paths, backup_dir)):
            stats["changed"] += 1

    # Remove files for notes/attachments that no longer exist (git history keeps them).
    for root in (notes_root, media_root):
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f not in expected:
                f.unlink()
        for d in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()

    return stats


def git(backup_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(backup_dir), *args],
        capture_output=True, text=True, check=check,
    )


def commit(backup_dir: Path, stats: dict) -> bool:
    if not (backup_dir / ".git").exists():
        git(backup_dir, "init", "-b", "main")
        log(f"Initialized git repo in {backup_dir}")
    gitignore = backup_dir / ".gitignore"
    if not gitignore.exists() or gitignore.read_text() != GITIGNORE:
        gitignore.write_text(GITIGNORE)
    git(backup_dir, "add", "-A")
    if not git(backup_dir, "status", "--porcelain").stdout.strip():
        return False
    msg = (
        f"Backup {datetime.now():%Y-%m-%d %H:%M} — "
        f"{stats['notes']} notes, {stats['attachments']} attachments"
    )
    git(backup_dir, "-c", "user.name=notes-backup",
        "-c", "user.email=notes-backup@localhost", "commit", "-q", "-m", msg)
    git(backup_dir, "gc", "--auto", "--quiet", check=False)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                    help=f"config file (default: {DEFAULT_CONFIG_PATH})")
    args = ap.parse_args()

    cfg = load_config(args.config)
    backup_dir: Path = cfg["backup_dir"]
    backup_dir.mkdir(parents=True, exist_ok=True)

    check_db_access()
    working_db = backup_dir / "snapshots" / "NoteStore-working.sqlite"
    working_db.parent.mkdir(parents=True, exist_ok=True)
    copy_live_db(working_db)
    snap = snapshot_db(backup_dir, working_db, list(cfg["db_snapshot_tiers"]))
    if snap:
        log(f"Database snapshot: {snap.name}")

    try:
        stats = export_notes(working_db, backup_dir, bool(cfg["commit_media"]))
    finally:
        working_db.unlink(missing_ok=True)
    log(f"Exported {stats['notes']} notes ({stats['changed']} changed), "
        f"{stats['attachments']} attachments"
        + (f", {stats['attachment_failures']} attachment(s) failed"
           if stats["attachment_failures"] else ""))

    if commit(backup_dir, stats):
        log("Committed changes to git.")
    else:
        log("No changes since last backup.")


if __name__ == "__main__":
    main()
