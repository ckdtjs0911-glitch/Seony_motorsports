"""Retain the current Korean calendar year and the previous two years."""
import json
import re
import shutil
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


def first_year(now=None):
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo("Asia/Seoul"))
    return now.year - 2


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def year_of(session):
    return session.get("year") or int(session["date_start"][:4])


def prune(reports, raw=None, now=None):
    cutoff = first_year(now)
    catalog = reports / "catalog" / "sessions.json"
    sessions = read(catalog) if catalog.exists() else []
    expired_keys = {s["session_key"] for s in sessions if year_of(s) < cutoff}
    removed = []
    for directory in sorted(reports.iterdir()) if reports.exists() else []:
        if not directory.is_dir() or directory.is_symlink():
            continue
        if re.fullmatch(r"weekend-\d+", directory.name):
            paths = sorted((directory / "data").glob("*.json"))
            snapshots = [(p, read(p)) for p in paths]
            known = [
                (p, v) for p, v in snapshots if isinstance(v, dict) and "session" in v
            ]
            for path, value in known:
                if year_of(value["session"]) < cutoff:
                    expired_keys.add(value["session"]["session_key"])
                    path.unlink()
                    removed.append(str(path))
            if (
                known
                and all(year_of(v["session"]) < cutoff for _, v in known)
                and len(known) == len(paths)
            ):
                shutil.rmtree(directory)
                removed.append(str(directory))
        elif (directory / "data" / "sessions.json").exists():
            # Legacy generated reports with a session-list metadata file.
            legacy = read(directory / "data" / "sessions.json")
            if (
                isinstance(legacy, list)
                and legacy
                and all(year_of(s) < cutoff for s in legacy)
            ):
                expired_keys.update(s["session_key"] for s in legacy)
                shutil.rmtree(directory)
                removed.append(str(directory))
    if raw and raw.exists():
        for directory in raw.iterdir():
            metadata = directory / "session.json"
            if (
                directory.name.isdigit()
                and directory.is_dir()
                and not directory.is_symlink()
                and metadata.exists()
            ):
                session = read(metadata)
                if year_of(session) < cutoff:
                    expired_keys.add(session["session_key"])
        for key in expired_keys:
            path = raw / str(key)
            if path.is_symlink():
                raise ValueError("Raw session directory must not be a symlink")
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(str(path))
        manifest = raw / "manifest.sqlite"
        if manifest.exists():
            with sqlite3.connect(manifest) as db:
                for key in expired_keys:
                    db.execute(
                        "DELETE FROM downloads WHERE job LIKE ?", (str(key) + "/%",)
                    )
    for name in ["sessions.json", "meetings.json", "archive-index.json"]:
        path = reports / "catalog" / name
        if path.exists():
            entries = read(path)
            retained = [s for s in entries if year_of(s) >= cutoff]
            if len(retained) != len(entries):
                path.write_text(
                    json.dumps(retained, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
    print(f"Retention: {cutoff} onward; removed {len(removed)} old paths")
    return removed
