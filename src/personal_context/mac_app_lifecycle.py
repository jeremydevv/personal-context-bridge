"""Restore GUI app state after read-only macOS automation."""

import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def collected_app(name, command="/usr/bin/osascript"):
    if name not in ("Contacts", "Notes"):
        raise ValueError("unsupported read-only automation app")
    # Full and fast sync have separate locks. Serialize each app's lifecycle.
    data_dir = Path(os.environ.get("PERSONAL_CONTEXT_DATA_DIR",
                                  Path.home() / ".local/share/personal-context-bridge"))
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    app = "Application(" + json.dumps(name) + ")"
    with (data_dir / (name.lower() + "-collect.lock")).open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        probe = subprocess.run([command, "-l", "JavaScript", "-e", app + ".running()"],
                               capture_output=True, text=True, timeout=30)
        if probe.returncode or probe.stdout.strip() not in ("true", "false"):
            raise RuntimeError("Cannot determine whether " + name + " was already running")
        already_running = probe.stdout.strip() == "true"
        try:
            if not already_running:
                launch = subprocess.run(["/usr/bin/open", "-g", "-a", name],
                                        capture_output=True, text=True, timeout=60)
                if launch.returncode:
                    raise RuntimeError("Cannot launch " + name + " before collection")
                # AppleEvents sent during an implicit cold launch can fail with
                # macOS -600. Wait for the app before the snapshot starts.
                for _ in range(20):
                    ready = subprocess.run([command, "-l", "JavaScript", "-e", app + ".running()"],
                                           capture_output=True, text=True, timeout=5)
                    if ready.returncode == 0 and ready.stdout.strip() == "true":
                        break
                    time.sleep(0.25)
                else:
                    raise RuntimeError(name + " did not become ready for collection")
            yield
        finally:
            if not already_running:
                original_error = sys.exc_info()[1]
                try:
                    cleanup = subprocess.run(
                        [command, "-l", "JavaScript", "-e",
                         'const app = ' + app + '; if (app.running()) app.quit();'],
                        capture_output=True, text=True, timeout=30)
                    if cleanup.returncode:
                        raise RuntimeError("Could not close " + name + " after collection")
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    if original_error is None:
                        raise
                    print(name + " cleanup failed: " + type(exc).__name__, file=sys.stderr)
