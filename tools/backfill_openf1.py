"""Resumable full OpenF1 JSON archive, including per-driver telemetry (rolling three years)."""
import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import weekend_report as report
from retention import first_year, prune

ENDPOINTS = (
    "drivers",
    "session_result",
    "laps",
    "stints",
    "pit",
    "race_control",
    "weather",
    "position",
    "intervals",
    "overtakes",
    "starting_grid",
    "championship_drivers",
    "championship_teams",
    "team_radio",
)


def run(root, reports, since=None, session_key=None, max_sessions=None):
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "manifest.sqlite")
    db.execute(
        "CREATE TABLE IF NOT EXISTS downloads (job TEXT PRIMARY KEY, status TEXT, records INTEGER, bytes INTEGER, sha256 TEXT)"
    )
    catalogs = {}
    for endpoint in ("meetings", "sessions"):
        path = reports / "catalog" / (endpoint + ".json")
        if path.exists():
            catalogs[endpoint] = report.load_json(path)
        else:
            catalogs[endpoint] = report.fetch(endpoint, {})
            report.save_json(path, catalogs[endpoint])
    prune(reports, root)
    since = max(since or first_year(), first_year())
    now = datetime.now(timezone.utc)
    sessions = [
        s
        for s in catalogs["sessions"]
        if s.get("year", 0) >= since
        and report.stamp(s["date_end"]) <= now
        and not s.get("is_cancelled")
        and (session_key is None or s["session_key"] == session_key)
    ]
    sessions.sort(key=lambda s: s["date_start"])
    if max_sessions:
        sessions = sessions[:max_sessions]

    def download(key, endpoint, driver=None):
        job = f"{key}/{endpoint}" + (f"-driver-{driver}" if driver is not None else "")
        path = root / (job + ".json.gz")
        previous = db.execute(
            "SELECT status, sha256 FROM downloads WHERE job=?", (job,)
        ).fetchone()
        if previous and previous[0] in ("complete", "empty") and path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() == previous[1]:
                with gzip.open(path, "rt", encoding="utf-8") as f:
                    return json.load(f)["data"]
        params = {"session_key": key}
        if driver is not None:
            params["driver_number"] = driver
        try:
            value = report.fetch(endpoint, params)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            db.execute(
                "INSERT OR REPLACE INTO downloads VALUES (?,?,?,?,?)",
                (job, f"http_{code}", 0, 0, ""),
            )
            db.commit()
            print(f"{job}: HTTP {code}", flush=True)
            if code in (401, 403, 429):
                raise RuntimeError(
                    f"Collection paused by API HTTP {code}; resume after access or rate limit changes"
                ) from None
            if code == 404:
                return None
            raise
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8") as f:
            json.dump(
                {
                    "endpoint": endpoint,
                    "params": params,
                    "fetched_at": now.isoformat(),
                    "data": value,
                },
                f,
                ensure_ascii=False,
            )
        temporary.replace(path)
        raw = path.read_bytes()
        db.execute(
            "INSERT OR REPLACE INTO downloads VALUES (?,?,?,?,?)",
            (
                job,
                "complete" if value else "empty",
                len(value),
                len(raw),
                hashlib.sha256(raw).hexdigest(),
            ),
        )
        db.commit()
        print(f"{job}: {len(value)} records, {len(raw)} compressed bytes", flush=True)
        return value

    for index, session in enumerate(sessions, 1):
        if session.get("year", 0) < first_year():
            prune(reports, root)
            continue
        key = session["session_key"]
        report.save_json(root / str(key) / "session.json", session)
        print(
            f'SESSION {index}/{len(sessions)}: {session["year"]} {session["location"]} {session["session_name"]} ({key})',
            flush=True,
        )
        data = {}
        for endpoint in ENDPOINTS:
            value = download(key, endpoint)
            if value is not None:
                data[endpoint] = value
            # Report data is available before optional datasets/telemetry finish.
            if all(name in data for name in report.ENDPOINTS):
                snapshot = {
                    "session": session,
                    "status": "수집 완료 (보고서 데이터 / 텔레메트리는 별도 원본)",
                    "fetched_at": now.isoformat(),
                    "data": {name: data[name] for name in report.ENDPOINTS},
                }
                report.save_json(
                    reports
                    / f'weekend-{session["meeting_key"]}'
                    / "data"
                    / f"{key}.json",
                    snapshot,
                )
        for driver in data.get("drivers", []):
            for endpoint in ("car_data", "location"):
                download(key, endpoint, driver["driver_number"])
        print(f"SESSION COMPLETE: {key}", flush=True)
        from build_archive import build

        build(reports, since)
    db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--since", type=int, default=None)
    p.add_argument("--raw-root", type=Path, default=report.ROOT.parent / "openf1-data")
    p.add_argument("--reports", type=Path, default=report.ROOT / "reports")
    p.add_argument("--session", type=int)
    p.add_argument("--max-sessions", type=int)
    args = p.parse_args()
    try:
        run(args.raw_root, args.reports, args.since, args.session, args.max_sessions)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(
            f"Stopped; downloaded files preserved: {exc}", file=sys.stderr, flush=True
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
