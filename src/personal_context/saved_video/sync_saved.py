"""Quiet unattended sync; authenticated collector exits before media processing."""

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

from .pipeline import DEFAULT_ALLOWLIST, DEFAULT_DATA, write_json

STATE = DEFAULT_ALLOWLIST.parent / "saved-video-sync.json"
HERE = Path(__file__).resolve().parent


def stamp():
    return datetime.now(timezone.utc).isoformat()


def _outcome(result, complete=False, emit=True, collection_finished=True):
    outcome = {'result': result, 'collection_finished': collection_finished,
               'coverage': 'complete' if complete else 'partial',
               'batch_ids': [], 'acked_batch_ids': [],
               'error_code': None if complete else result}
    identity = {key: os.environ.get(env, '') for key, env in (
        ('refresh_id', 'PERSONAL_CONTEXT_REFRESH_ID'),
        ('attempt_id', 'PERSONAL_CONTEXT_REFRESH_ATTEMPT'),
        ('source', 'PERSONAL_CONTEXT_REFRESH_SOURCE'))}
    if emit and all(identity.values()) and identity['source'] == 'saved_video':
        print(json.dumps({**identity, **outcome}), flush=True)
    return outcome


def run():
    os.umask(0o077)
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE.parent / "saved-video-sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return _outcome('lock_busy', emit=False, collection_finished=False)
        # Final receipt is emitted before releasing this invocation's lock.
        return _run_locked()


def _report_identity(path):
    try:
        stat = path.stat()
        return stat.st_ino, stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return None


def _run_locked():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state.update(enabled=True, interval_minutes=30, checked_at=stamp())
    if state.get("collection_retry_after", 0) > time.time():
        state["result"] = "collection_cooldown"
        write_json(STATE, state)
        return _outcome(state["result"])
    # Neither environment nor stdout carries cookies into the downloader.
    environment = {
        k: os.environ[k]
        for k in (
            "HOME",
            "PATH",
            "LANG",
            "XDG_RUNTIME_DIR",
            "PERSONAL_CONTEXT_KEY_FILE",
            "PERSONAL_CONTEXT_DB",
            "SAVED_VIDEO_ALLOWLIST",
            "SAVED_VIDEO_DATA",
            "SAVED_VIDEO_ARCHIVE",
            "SAVED_VIDEO_INSTAGRAM_PROFILE",
            "SAVED_VIDEO_FFMPEG",
        )
        if k in os.environ
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "personal_context.saved_video.collect_saved"],
            capture_output=True,
            text=True,
            env=environment,
            timeout=360,
        )
        collection = json.loads(result.stdout)
        if result.returncode != 0 or not isinstance(collection, dict):
            raise ValueError("collector_process_failed")
    except Exception:
        collection = {
            "ok": False,
            "reason": "collector_process_failed",
            "cooldown_seconds": 3600,
        }
    if not collection.get("ok"):
        state.update(
            result="collection_failed",
            error=collection.get("reason", "collection_failed"),
            collection_retry_after=time.time()
            + collection.get("cooldown_seconds", 3600),
        )
        write_json(STATE, state)
        return _outcome(state["result"])
    state.update(
        last_saved_check_succeeded_at=stamp(),
        collection=collection,
        collection_retry_after=0,
    )
    state.pop("error", None)
    digest = collection["allowlist_sha256"]
    if (
        digest == state.get("processed_allowlist_sha256")
        and state.get("processing_retry_after", 0) > time.time()
    ):
        state["result"] = "processing_cooldown"
        write_json(STATE, state)
        return _outcome(state["result"])
    if digest == state.get("processed_allowlist_sha256") and state.get(
        "last_processing_ok"
    ):
        state["result"] = "unchanged"
        write_json(STATE, state)
        return _outcome(state["result"], complete=True)
    state["result"] = "processing"
    write_json(STATE, state)
    report_path = DEFAULT_DATA / "run-report.json"
    previous_report = _report_identity(report_path)
    try:
        # Only metadata is printed by the processor; do not persist raw exceptions.
        result = subprocess.run(
            [sys.executable, "-m", "personal_context.saved_video.pipeline", "run"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=4 * 3600,
        )
        report = json.loads(report_path.read_text())
        ok = (
            result.returncode == 0
            and _report_identity(report_path) != previous_report
            and report["total"] == report["complete"]
            and report["failed"] == 0
            and report["allowlist_sha256"] == digest
        )
    except Exception:
        ok = False
    state.update(
        result="complete" if ok else "processing_incomplete",
        last_processing_ok=ok,
        processed_allowlist_sha256=digest,
        last_processing_at=stamp(),
        processing_retry_after=0 if ok else time.time() + 6 * 3600,
    )
    write_json(STATE, state)

    return _outcome(state["result"], complete=ok)


def main():
    # Console scripts call sys.exit; keep result metadata out of stderr/status.
    run()


if __name__ == "__main__":
    main()
