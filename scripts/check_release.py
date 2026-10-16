#!/usr/bin/env python3
"""Check tracked source for runtime artifacts and common credential patterns.

Optional PERSONAL_CONTEXT_PRIVATE_MARKERS contains newline-separated private
strings. Failures print paths/line numbers only, never matching values.
This is a release guardrail; human privacy review is still required.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile
import argparse

ROOT = Path(__file__).resolve().parents[1]
BAD_PARTS = {
    "data",
    "runtime",
    "backups",
    "private",
    ".venv",
    "__pycache__",
    "instagram-profile",
    "firefox-profile",
    "browser-state",
    "saved-video-staging",
    "saved-videos",
    "exports",
    "archives",
    "media",
    "frames",
    "models",
    "screenshots",
    "spool",
}
BAD_SUFFIX = (
    ".key",
    ".token",
    ".cred",
    ".pem",
    ".blob",
    ".sqlite3",
    ".sqlite",
    ".db",
    ".pyc",
    ".log",
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".wav",
    ".mp3",
    ".m4a",
    ".srt",
    ".onnx",
    ".safetensors",
    ".har",
    ".pcap",
    ".session",
    ".pfx",
)
BAD_NAMES = {
    "cookies.txt",
    "cookies.json",
    "cookies.sqlite",
    "saved-video-urls.txt",
    "saved-video-sync.json",
    ".env",
    "storage-state.json",
}
PATTERNS = [
    re.compile(x)
    for x in (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
        r"\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}\b",
        r"(?:/Users/|/home/)[A-Za-z0-9_.-]+/",
        r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b",
        r"\bsessionid\s*[:=]\s*[\"\x27]?[A-Za-z0-9%:_-]{24,}",
    )
]
MARKERS = [
    x for x in os.environ.get("PERSONAL_CONTEXT_PRIVATE_MARKERS", "").splitlines() if x
]


def issues(name, data):
    path = Path(name)
    findings = []
    if (
        BAD_PARTS.intersection(path.parts)
        or name.endswith(BAD_SUFFIX)
        or path.name in BAD_NAMES
        or re.search(r"\.(sqlite\w*|db)(-wal|-shm|-journal)?$", path.name)
    ):
        findings.append(name + ": runtime artifact")
    if b"\x00" in data:
        findings.append(name + ": unexpected binary content")
        return findings
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError:
        return findings + [name + ": non-UTF-8 file requires review"]
    for number, line in enumerate(source.splitlines(), 1):
        if any(pattern.search(line) for pattern in PATTERNS) or any(
            marker.casefold() in line.casefold() for marker in MARKERS
        ):
            findings.append(f"{name}:{number}: sensitive pattern requires review")
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        action="store_true",
        help="Audit every reachable Git blob, including deleted files",
    )
    args = parser.parse_args()
    names = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    names = [name for name in names if name]
    if not names:
        raise SystemExit(
            "No tracked files; stage intended source before checking release"
        )
    failures = []
    for name in names:
        path = ROOT / name
        if path.is_symlink():
            failures.append(name + ": symlink is not allowed")
            continue
        failures.extend(issues(name, path.read_bytes()))
        # The exact staged bytes also matter when the worktree differs.
        indexed = subprocess.check_output(["git", "show", ":" + name], cwd=ROOT)
        failures.extend(issues(name, indexed))
    history_blobs = 0
    if args.history:
        objects = (
            subprocess.check_output(["git", "rev-list", "--objects", "--all"], cwd=ROOT)
            .decode()
            .splitlines()
        )
        for line in objects:
            object_id, _, name = line.partition(" ")
            kind = subprocess.check_output(
                ["git", "cat-file", "-t", object_id], cwd=ROOT
            ).strip()
            if kind != b"blob":
                continue
            history_blobs += 1
            data = subprocess.check_output(
                ["git", "cat-file", "blob", object_id], cwd=ROOT
            )
            failures.extend(issues(name, data))
    for package in sorted((ROOT / "dist").glob("*")):
        if package.suffix == ".whl":
            with zipfile.ZipFile(package) as archive:
                for info in archive.infolist():
                    if not info.is_dir():
                        failures.extend(issues(info.filename, archive.read(info)))
        elif package.name.endswith(".tar.gz"):
            with tarfile.open(package) as archive:
                for info in archive.getmembers():
                    if info.isfile():
                        failures.extend(
                            issues(info.name, archive.extractfile(info).read())
                        )
                    elif info.issym() or info.islnk():
                        failures.append(info.name + ": archive link is not allowed")
    if failures:
        print("\n".join(sorted(set(failures))))
        return 1
    print(
        f"Release privacy check passed: {len(names)} tracked/index files, {history_blobs} historical blobs, and distribution archives"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
