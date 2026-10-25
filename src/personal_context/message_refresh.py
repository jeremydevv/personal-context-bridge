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
    """Queue a durable Messages-only request; target remains API-compatible."""
    from .refresh_tracking import request_refresh as durable_request
    return durable_request(['message'])


def run_mac_refresh(config_path=None, data_dir=None):
    """Serialize with the fast lane, then collect only Messages text and metadata."""
    config_path = Path(config_path or CONFIG_DIR / "config.json")
    data_dir = Path(data_dir or DATA_DIR)
    config = load_config(config_path)
    if not config.get("all_messages"):
        raise ValueError("Messages collection is disabled")
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    data_dir.chmod(0o700)
    from .refresh_worker import resource_lock
    with resource_lock(data_dir / "refresh-collection.lock"), resource_lock(data_dir / "sync-fast.lock"):
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
