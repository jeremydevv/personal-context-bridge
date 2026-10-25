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
    if name not in ("Contacts", "Notes", "Mail"):
        raise ValueError("unsupported read-only automation app")
    # Full and fast sync have separate locks. Serialize each app's lifecycle.
    data_dir = Path(os.environ.get("PERSONAL_CONTEXT_DATA_DIR",
                                  Path.home() / ".local/share/personal-context-bridge"))
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    app = "Application(" + json.dumps(name) + ")"
    with (data_dir / (name.lower() + "-collect.lock")).open("a+b") as lock:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise RuntimeError('app_collection_busy')
                time.sleep(.05)
        probe = subprocess.run([command, "-l", "JavaScript", "-e", app + ".running()"],
                               capture_output=True, text=True, timeout=30)
        if probe.returncode or probe.stdout.strip() not in ("true", "false"):
            raise RuntimeError("Cannot determine whether " + name + " was already running")
        already_running = probe.stdout.strip() == "true"
        receipt = {'app': name, 'initial_running': already_running,
                   'launched_by_collector': False, 'launch_mode': 'background',
                   'final_running': None, 'cleanup': 'pending'}
        try:
            if not already_running:
                launch = subprocess.run(["/usr/bin/open", "-g", "-a", name],
                                        capture_output=True, text=True, timeout=60)
                if launch.returncode:
                    raise RuntimeError("Cannot launch " + name + " before collection")
                receipt['launched_by_collector'] = True
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
            yield receipt
        finally:
            if already_running:
                try:
                    final = subprocess.run([command, "-l", "JavaScript", "-e", app + ".running()"],
                                           capture_output=True, text=True, timeout=30)
                    receipt['final_running'] = final.stdout.strip() == 'true' if final.returncode == 0 and final.stdout.strip() in ('true','false') else None
                    receipt['cleanup'] = 'preserved_initial' if receipt['final_running'] is not None else 'failed'
                except (OSError, subprocess.TimeoutExpired):
                    receipt['cleanup'] = 'failed'
            else:
                original_error = sys.exc_info()[1]
                try:
                    condition = "app.running()"
                    if name == "Mail":
                        from .mail_collect import wait_for_mail_idle
                        wait_for_mail_idle()
                        # Preserve composition and a user who brought Mail forward.
                        condition += " && !app.frontmost() && app.outgoingMessages().length === 0"
                    cleanup = subprocess.run(
                        [command, "-l", "JavaScript", "-e",
                         'const app = ' + app + '; const wasRunning = app.running(); '
                         'const permitted = (' + condition + '); if (permitted) app.quit(); '
                         'JSON.stringify({final_running: app.running(), cleanup: '
                         '(!wasRunning || permitted) ? "closed" : "preserved_for_user"})'],
                        capture_output=True, text=True, timeout=30)
                    if cleanup.returncode:
                        raise RuntimeError("Could not close " + name + " after collection")
                    try:
                        details = json.loads(cleanup.stdout)
                        if isinstance(details, dict) and isinstance(details.get('final_running'), bool) and details.get('cleanup') in ('closed','preserved_for_user'):
                            receipt.update(details)
                            if details['cleanup'] == 'closed' and details['final_running']:
                                receipt['cleanup'] = 'failed'
                        else: receipt['cleanup'] = 'failed'
                    except (ValueError, TypeError):
                        receipt['cleanup'] = 'failed'
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    receipt['cleanup'] = 'failed'
                    if original_error is None:
                        raise
                    print(name + " cleanup failed: " + type(exc).__name__, file=sys.stderr)
