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
import hashlib
import gzip
import zlib

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
# Reviewed generated repository artwork; exact hashes keep binary exemptions narrow.
PUBLIC_ARTWORK = {
    "docs/assets/banners/01-paper-archive.png": "ed6baf1b8a3c8c83104b90a3e3e371d2778c8362892d662fbff8a314d6f66608",
    "docs/assets/banners/02-glass-bridge.png": "fadbc2f82affbcb8c03e4ed85fe063ee6b27640e130391c7ccfb29809dad8079",
    "docs/assets/banners/03-constellation.png": "302f6dc2c2aae2c29d9bb97e6dd918502c203a895ba59eef81bb51909f33d9ee",
    "docs/assets/banners/04-field-guide.png": "a778de9205a90e377676caf15bd4092845f085f4b6bd26a40732a6f5de9b86b1",
    "docs/assets/banners/05-blueprint.png": "ca1c891253a820996264d30fd2175b0c2fccf2f60cd0d95cb744d4e2c32879df",
}

MARKERS = [
    x for x in os.environ.get("PERSONAL_CONTEXT_PRIVATE_MARKERS", "").splitlines() if x
]


def neutral_gzip_metadata(package):
    """Require one gzip member with no optional identity-bearing header fields."""
    with open(package, 'rb') as raw:
        header = raw.read(10)
        if len(header) != 10 or header[:4] != b'\x1f\x8b\x08\x00':
            return False
        raw.seek(0)
        decoder = zlib.decompressobj(31)
        while data := raw.read(65536):
            while data:
                decoder.decompress(data, 65536)
                if decoder.eof:
                    return not decoder.unused_data and not raw.read(1)
                data = decoder.unconsumed_tail
        return False


def tar_metadata_issues(package):
    """Check physical headers too: effective PAX fields can hide earlier owners.

    Only ordinary files/directories and local path/mtime PAX records are supported.
    Diagnostic text never contains header values or extension payloads.
    """
    failure = str(Path(package).name) + ': archive metadata requires review'
    try:
        if not neutral_gzip_metadata(package):
            return [failure]
        with gzip.open(package, 'rb') as stream:
            while True:
                block = stream.read(512)
                if block == b'\0' * 512:
                    # No unreviewed appended tar, gzip member or trailing payload.
                    while tail := stream.read(65536):
                        if tail.strip(b'\0'):
                            return [failure]
                    return []
                if len(block) != 512:
                    return [failure]
                # Parsed strings truncate at NUL; inspect the full owner fields.
                neutral_owners = (b'\0' * 32, b'root' + b'\0' * 28)
                if block[265:297] not in neutral_owners or block[297:329] not in neutral_owners:
                    return [failure]
                header = tarfile.TarInfo.frombuf(block, 'utf-8', 'strict')
                if (header.uid != 0 or header.gid != 0
                        or header.uname not in ('', 'root') or header.gname not in ('', 'root')
                        or header.type not in (tarfile.REGTYPE, tarfile.AREGTYPE,
                                               tarfile.DIRTYPE, tarfile.XHDTYPE)):
                    return [failure]
                if issues(header.name, b'') or header.linkname or header.size < 0:
                    return [failure]
                if header.type == tarfile.XHDTYPE:
                    if header.size > 65536:
                        return [failure]
                    data = stream.read(header.size)
                    position = 0
                    while position < len(data):
                        space = data.find(b' ', position)
                        if space < 0:
                            return [failure]
                        length = int(data[position:space])
                        end = position + length
                        if end > len(data) or end <= space + 1 or data[end-1:end] != b'\n':
                            return [failure]
                        key, separator, value = data[space+1:end-1].partition(b'=')
                        if not separator or key not in (b'path', b'mtime') or issues('archive-metadata', value):
                            return [failure]
                        if key == b'mtime' and not re.fullmatch(rb'-?\d+(?:\.\d+)?', value):
                            return [failure]
                        position = end
                    if len(data) != header.size:
                        return [failure]
                else:
                    stream.seek(header.size, 1)
                stream.seek((-header.size) % 512, 1)
    except (OSError, EOFError, ValueError, UnicodeError, tarfile.TarError, zlib.error):
        return [failure]


def issues(name, data):
    if name in PUBLIC_ARTWORK:
        if hashlib.sha256(data).hexdigest() == PUBLIC_ARTWORK[name]:
            return []
        return [name + ": artwork changed; binary review required"]
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
            failures.extend(tar_metadata_issues(package))
            with tarfile.open(package) as archive:
                for info in archive.getmembers():
                    failures.extend(issues(info.name, b''))
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
