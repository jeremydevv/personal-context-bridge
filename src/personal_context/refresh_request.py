"""Approval-gated requests for fixed collection jobs; acceptance is not completion."""

import os
import re
import subprocess


MAC_JOBS = {
    "apple": "org.personalcontext.personal-context-fast-sync",
    "canvas": "org.personalcontext.personal-context-canvas-sync",
}
OBSIDIAN_UNIT = "obsidian-icloud-sync.service"


def request_mac_refresh(job, target=None):
    if job not in MAC_JOBS:
        raise ValueError("unsupported refresh job")
    target = target if target is not None else os.environ.get("PERSONAL_CONTEXT_REFRESH_TARGET", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*", target):
        raise ValueError("Mac refresh SSH target is not configured")
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=5", "-o", "ConnectionAttempts=1", target,
               "launchctl kickstart gui/$(id -u)/" + MAC_JOBS[job]]
    try:
        result = subprocess.run(command, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return {"requested": False, "state": "mac_unreachable_or_job_unavailable"}
    return ({"requested": True, "state": "accepted_by_launchd"} if result.returncode == 0
            else {"requested": False, "state": "mac_unreachable_or_job_unavailable"})


def request_obsidian_refresh():
    try:
        result = subprocess.run(["systemctl", "--user", "start", "--no-block", OBSIDIAN_UNIT],
                                capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return {"requested": False, "state": "sync_job_unavailable"}
    return ({"requested": True, "state": "accepted_by_systemd"} if result.returncode == 0
            else {"requested": False, "state": "sync_job_unavailable"})
