"""Mirror encrypted iPhone archive snapshots to the FileVault Mac when awake."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time


LOCAL_ROOT = Path.home() / ".local/share/iphone-context-bridge/backups"
CONFIG = Path.home() / ".config/personal-context-bridge/config.json"
REMOTE_ROOT = Path(os.environ.get("IPHONE_REMOTE_ROOT", "/srv/iphone-context-bridge"))
REMOTE_PYTHON = Path(os.environ.get("IPHONE_REMOTE_PYTHON", "/srv/personal-context-bridge/.venv/bin/python"))
REMOTE_DATA = Path(os.environ.get("IPHONE_REMOTE_DATA_DIR", str(REMOTE_ROOT / "data")))
REMOTE_KEY = os.environ.get("IPHONE_REMOTE_KEY_FILE", "/run/personal-context-bridge/archive.key")
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1"]
MAX_TOTAL_BYTES = 20 * 1024**3
MIN_FREE_BYTES = 8 * 1024**3


def checked_remote_path(source: str, value: str, base=None) -> str:
    if source not in ("health", "travel") or not isinstance(value, str):
        raise ValueError("invalid archive source or path")
    pattern = (re.escape(str(Path(base) / "backups")) + "/" + source +
               r"/backup-[0-9]+-[0-9a-f]{32}\.sqlite3") if base is not None else (r"data/backups/" + source +
               r"/backup-[0-9]+-[0-9a-f]{32}\.sqlite3")
    if not re.fullmatch(pattern, value):
        raise ValueError("remote backup path is outside the expected source directory")
    return value


def prune_local_copies(directory, incoming_bytes=0, retain=7,
                       max_total_bytes=MAX_TOTAL_BYTES,
                       min_free_bytes=MIN_FREE_BYTES):
    directory = Path(directory)
    if directory.is_symlink() or not 2 <= retain <= 30:
        raise ValueError("invalid backup directory or retention")
    copies = sorted(directory.glob("*.sqlite3"))
    if any(path.is_symlink() for path in copies):
        raise ValueError("backup directory contains a symlink")
    target_count = retain - (1 if incoming_bytes else 0)
    while len(copies) > 1 and (
            len(copies) > target_count
            or sum(path.stat().st_size for path in copies) + incoming_bytes > max_total_bytes
            or (incoming_bytes and shutil.disk_usage(directory).free < incoming_bytes + min_free_bytes)):
        copies.pop(0).unlink()
    if incoming_bytes and sum(path.stat().st_size for path in copies) + incoming_bytes > max_total_bytes:
        raise RuntimeError("encrypted iPhone backup would exceed the Mac retention cap")
    if incoming_bytes and shutil.disk_usage(directory).free < incoming_bytes + min_free_bytes:
        raise RuntimeError("insufficient Mac space for encrypted iPhone archive backup")


def run(command, timeout=3600):
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("backup command failed: " + command[0])
    return result.stdout.decode("utf-8").strip()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mirror_source(host: str, source: str, run_command=run) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
        raise ValueError("invalid configured remote host")
    if source not in ("health", "travel"):
        raise ValueError("invalid iPhone archive source")
    remote_command = ("cd " + shlex.quote(str(REMOTE_ROOT)) + " && "
                      + shlex.quote(str(REMOTE_PYTHON)) + " -m iphone_context.archive_backup"
                      + " --source " + source + " --data-dir " + shlex.quote(str(REMOTE_DATA)) + " --key-file " + shlex.quote(REMOTE_KEY))
    result = json.loads(run_command(["ssh", *SSH_OPTIONS, host, remote_command]))
    path = checked_remote_path(source, result.get("path"), base=REMOTE_DATA)
    size = result.get("bytes")
    if result.get("ok") is not True or isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= 100 * 1024**3:
        raise RuntimeError("remote encrypted backup report is invalid")
    directory = LOCAL_ROOT / source
    if LOCAL_ROOT.is_symlink() or directory.is_symlink():
        raise ValueError("local backup path cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    prune_local_copies(directory, incoming_bytes=size)
    remote_file = str(REMOTE_ROOT / path)
    destination = directory / (str(time.time_ns()) + ".sqlite3")
    temporary = destination.with_suffix(".tmp")
    try:
        run_command(["scp", *SSH_OPTIONS, host + ":" + remote_file, str(temporary)], timeout=8 * 3600)
        temporary.chmod(0o600)
        if temporary.stat().st_size != size:
            raise RuntimeError("encrypted backup transfer size mismatch")
        remote_hash = run_command(["ssh", *SSH_OPTIONS, host,
                                   "sha256sum " + shlex.quote(remote_file)]).split()[0]
        if sha256_file(temporary) != remote_hash:
            raise RuntimeError("encrypted backup transfer checksum mismatch")
        os.replace(temporary, destination)
        prune_local_copies(directory)
        return {"source": source, "bytes": size, "local_copies": len(list(directory.glob("*.sqlite3")))}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    if LOCAL_ROOT.is_symlink():
        raise ValueError("local backup directory cannot be a symlink")
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOCAL_ROOT.chmod(0o700)
    config = json.loads(CONFIG.read_text())
    host = config["remote_host"]
    with (LOCAL_ROOT / "mirror.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"already_running": True}))
            return 0
        results = []
        failed = []
        for source in ("health", "travel"):
            try:
                results.append(mirror_source(host, source))
            except (ValueError, RuntimeError, subprocess.TimeoutExpired, OSError):
                failed.append(source)
        print(json.dumps({"mirrored": results, "failed": failed}))
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
