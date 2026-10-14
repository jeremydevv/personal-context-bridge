"""Request a Mac Messages collection from the private Messages MCP service."""

import argparse
import fcntl
import os
import re
import subprocess
import sys
from pathlib import Path

from .cli import load_config


LABEL = "org.personalcontext.personal-context-message-refresh"
CONFIG_DIR = Path.home() / ".config/personal-context-bridge"
DATA_DIR = Path.home() / ".local/share/personal-context-bridge"


def request_refresh(target=None):
    """Ask launchd to start the fixed Messages-only job; do not claim completion."""
    target = target if target is not None else os.environ.get("PERSONAL_CONTEXT_MESSAGE_REFRESH_TARGET", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*", target):
        raise ValueError("Messages refresh SSH target is not configured")
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=5", "-o", "ConnectionAttempts=1", target,
               "launchctl kickstart gui/$(id -u)/" + LABEL]
    try:
        result = subprocess.run(command, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return {"requested": False, "state": "mac_unreachable_or_job_unavailable"}
    if result.returncode:
        return {"requested": False, "state": "mac_unreachable_or_job_unavailable"}
    return {"requested": True, "state": "accepted_by_launchd"}


def run_mac_refresh(config_path=None, data_dir=None):
    """Serialize with the fast lane, then collect only Messages text and metadata."""
    config_path = Path(config_path or CONFIG_DIR / "config.json")
    data_dir = Path(data_dir or DATA_DIR)
    config = load_config(config_path)
    if not config.get("all_messages"):
        raise ValueError("Messages collection is disabled")
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    data_dir.chmod(0o700)
    with (data_dir / "sync-fast.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        typedstream_site = Path(sys.prefix) / ("lib/python%d.%d/site-packages" % sys.version_info[:2])
        env = dict(os.environ, PERSONAL_CONTEXT_SYNC_LANE="fast")
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (env.get("PYTHONPATH", ""),
                                                        str(typedstream_site))))
        result = subprocess.run([sys.executable, "-m", "personal_context.cli", "messages-sync",
                                 "--config", str(config_path)], env=env,
                                capture_output=True, timeout=3600)
        if result.returncode:
            raise RuntimeError("Messages collection failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-mac", action="store_true", required=True)
    parser.parse_args()
    run_mac_refresh()


if __name__ == "__main__":
    main()
