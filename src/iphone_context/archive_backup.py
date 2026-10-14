"""Make verified, rotating SQLCipher snapshots of the iPhone archives.

The source may have an active writer. SQLite's online backup API captures a
consistent view, and SQLCipher encrypts the destination with the same key.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import uuid


def snapshot_archive(source_path, key_path, backup_dir, retain: int = 7) -> dict:
    from sqlcipher3 import dbapi2 as cipher

    source_path, key_path, backup_dir = map(Path, (source_path, key_path, backup_dir))
    if not source_path.is_file() or source_path.is_symlink():
        raise ValueError("source archive must be an existing regular file")
    if not key_path.is_file() or key_path.is_symlink() or key_path.stat().st_mode & 0o077:
        raise ValueError("runtime archive key must be a private regular file")
    if isinstance(retain, bool) or not isinstance(retain, int) or not 2 <= retain <= 30:
        raise ValueError("retain must be between 2 and 30")
    key = key_path.read_bytes()
    if len(key) != 32:
        raise ValueError("runtime archive key must contain 32 bytes")
    if backup_dir.is_symlink():
        raise ValueError("backup directory cannot be a symlink")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir.chmod(0o700)
    stamp = str(time.time_ns()) + "-" + uuid.uuid4().hex
    temporary = backup_dir / ("backup-" + stamp + ".tmp")
    finished = backup_dir / ("backup-" + stamp + ".sqlite3")
    source = target = None
    try:
        source = cipher.connect(f"file:{source_path.absolute()}?mode=ro", uri=True)
        source.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
        source.execute("SELECT count(*) FROM sqlite_master").fetchone()
        target = cipher.connect(str(temporary))
        target.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
        source.backup(target)
        target.close()
        target = None
        source.close()
        source = None
        temporary.chmod(0o600)
        with temporary.open("rb") as stream:
            if stream.read(16) == b"SQLite format 3\x00":
                raise RuntimeError("snapshot is unexpectedly plaintext")
            os.fsync(stream.fileno())
        verify = cipher.connect(f"file:{temporary.absolute()}?mode=ro", uri=True)
        try:
            verify.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
            if verify.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("snapshot integrity check failed")
        finally:
            verify.close()
        os.replace(temporary, finished)
        directory_fd = os.open(backup_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        copies = sorted(backup_dir.glob("backup-*.sqlite3"))
        for old in copies[:-retain]:
            old.unlink()
        return {"ok": True, "path": str(finished), "bytes": finished.stat().st_size,
                "retained": len(list(backup_dir.glob("backup-*.sqlite3")))}
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("health", "travel"), required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--key-file", required=True)
    args = parser.parse_args(argv)
    data = Path(args.data_dir)
    name = "health.sqlite3" if args.source == "health" else "travel.sqlite3"
    print(json.dumps(snapshot_archive(data / name, args.key_file,
                                      data / "backups" / args.source)))


if __name__ == "__main__":
    main()
