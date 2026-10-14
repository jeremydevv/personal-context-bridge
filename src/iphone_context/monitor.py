"""Check iPhone archive availability without logging health or location records."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


SERVICES = (
    "iphone-health-ingest.service",
    "iphone-location-ingest.service",
    "iphone-context-health-tunnel.service",
    "iphone-context-travel-tunnel.service",
    "iphone-archive-backup@health.timer",
    "iphone-archive-backup@travel.timer",
)
ARCHIVES = {"health": "health.sqlite3", "travel": "travel.sqlite3"}


def assess(backups: dict[str, list[float]], active: dict[str, bool],
           archive_ok: dict[str, bool], now: float,
           max_backup_age_hours: int = 36) -> dict:
    if max_backup_age_hours < 24:
        raise ValueError("backup age threshold must cover the daily backup interval")
    problems = []
    for service in SERVICES:
        if not active.get(service, False):
            problems.append("inactive:" + service)
    backup_age = {}
    for source in ARCHIVES:
        if not archive_ok.get(source, False):
            problems.append("unreadable_archive:" + source)
        stamps = backups.get(source, [])
        age = None if not stamps else max(0, round((now - max(stamps)) / 3600, 2))
        backup_age[source] = age
        if age is None or age > max_backup_age_hours:
            problems.append("missing_or_stale_backup:" + source)
    return {"ok": not problems, "problems": problems,
            "backup_age_hours": backup_age}


def archive_readable(path: Path, key: bytes, source: str) -> bool:
    from sqlcipher3 import dbapi2 as cipher

    if not path.is_file() or path.is_symlink():
        return False
    db = None
    try:
        db = cipher.connect(f"file:{path.absolute()}?mode=ro", uri=True)
        db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
        db.execute("PRAGMA query_only=ON")
        if source == "health":
            db.execute("SELECT count(*) FROM batches").fetchone()
        else:
            db.execute("SELECT count(*) FROM events").fetchone()
        return True
    except cipher.DatabaseError:
        return False
    finally:
        if db is not None:
            db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--max-backup-age-hours", type=int, default=36)
    args = parser.parse_args(argv)
    data = Path(args.data_dir)
    key_path = Path(args.key_file)
    if not key_path.is_file() or key_path.is_symlink() or key_path.stat().st_mode & 0o077:
        raise RuntimeError("private runtime archive key is required")
    key = key_path.read_bytes()
    if len(key) != 32:
        raise RuntimeError("runtime archive key must contain 32 bytes")
    now = time.time()
    active = {service: subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", service],
        check=False, timeout=15).returncode == 0 for service in SERVICES}
    backups = {source: [path.stat().st_mtime for path in
                        (data / "backups" / source).glob("backup-*.sqlite3")
                        if path.is_file() and not path.is_symlink()]
               for source in ARCHIVES}
    archive_ok = {source: archive_readable(data / name, key, source)
                  for source, name in ARCHIVES.items()}
    report = assess(backups, active, archive_ok, now, args.max_backup_age_hours)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
