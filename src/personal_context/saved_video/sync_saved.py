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


def run():
    os.umask(0o077)
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (STATE.parent / "saved-video-sync.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state.update(enabled=True, interval_minutes=30, checked_at=stamp())
    if state.get("collection_retry_after", 0) > time.time():
        state["result"] = "collection_cooldown"
        write_json(STATE, state)
        return
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
        return
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
        return
    if digest == state.get("processed_allowlist_sha256") and state.get(
        "last_processing_ok"
    ):
        state["result"] = "unchanged"
        write_json(STATE, state)
        return
    state["result"] = "processing"
    write_json(STATE, state)
    try:
        # Only metadata is printed by the processor; do not persist raw exceptions.
        result = subprocess.run(
            [sys.executable, "-m", "personal_context.saved_video.pipeline", "run"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=4 * 3600,
        )
        report = json.loads((DEFAULT_DATA / "run-report.json").read_text())
        ok = (
            result.returncode == 0
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


if __name__ == "__main__":
    run()
