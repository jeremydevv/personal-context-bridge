"""Encrypted, deduplicated Saved evidence; plaintext exists only in private tmpfs.

Preserve source MP4 bytes. Store sampled timestamps and OCR, regenerate images
on demand rather than keeping hundreds of duplicate JPEGs and contact sheets.
"""

import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import zipfile
import shutil

from .pipeline import Pipeline, SavedPolicy, DEFAULT_ALLOWLIST, DEFAULT_DATA, write_json

from ..blob_store import BlobStore

DEFAULT_ARCHIVE = Path(
    os.environ.get(
        "SAVED_VIDEO_ARCHIVE",
        Path(
            os.environ.get(
                "PERSONAL_CONTEXT_DB",
                Path.home() / ".local/share/personal-context-bridge/context.sqlite3",
            )
        ).parent
        / "saved-videos",
    )
)
MAX_BUNDLE = 512 * 1024 * 1024
MAX_INDEX = 16 * 1024 * 1024


def key_bytes():
    return Path(os.environ["PERSONAL_CONTEXT_KEY_FILE"]).read_bytes()


def packed_json(value):
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    if len(raw) > MAX_INDEX:
        raise ValueError("Expanded index exceeds storage limit")
    return gzip.compress(raw, mtime=0)


def build_archive(p, root, key, allow_incomplete=False):
    root = Path(root)
    blobs = BlobStore(root / "objects", key)
    index = {"version": 1, "videos": []}
    previous = Archive(p.policy, root, key) if (root / "index.ref").exists() else None
    source_bytes = retained_bytes = 0
    for v in p.list_videos():
        if v["status"] != "complete":
            if previous and v["id"] in previous.entries and v["status"] == "pending":
                item = previous.entry(v["id"])
                # Reuse immutable encrypted bundles on incremental imports.
                retained_bytes += len(blobs.read(item["object_id"], MAX_BUNDLE))
                source_bytes += item.get("source_bytes", 0)
                index["videos"].append(item)
                continue
            if allow_incomplete:
                continue
            raise ValueError("All Saved videos must be complete before archival")
        directory = p.path(v["id"])
        transcript = json.loads((directory / "transcript.json").read_text())
        ocr = json.loads((directory / "ocr.json").read_text())
        names = {"manifest.json", "transcript.json", "ocr.json"}
        if (directory / "network-audit.json").exists():
            names.add("network-audit.json")
        names.update(a["media"] for a in v["assets"])
        # No duplicated per-asset transcript, SRT, frames, storyboards or moments.
        buffer = io.BytesIO()
        hashes = {}
        with zipfile.ZipFile(buffer, "w") as output:
            for name in sorted(names):
                source = directory / name
                if (
                    source.is_symlink()
                    or source.resolve().parent != directory.resolve()
                ):
                    raise ValueError("Unsafe archive source")
                data = source.read_bytes()
                hashes[name] = hashlib.sha256(data).hexdigest()
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = (
                    zipfile.ZIP_STORED
                    if name.endswith(".mp4")
                    else zipfile.ZIP_DEFLATED
                )
                output.writestr(info, data)
        bundle = buffer.getvalue()
        if len(bundle) > MAX_BUNDLE:
            raise ValueError("Video bundle exceeds storage limit")
        metadata = blobs.ingest(io.BytesIO(bundle), MAX_BUNDLE)
        # Authenticate/decrypt and verify every retained source before publishing.
        with zipfile.ZipFile(
            io.BytesIO(blobs.read(metadata["object_id"], MAX_BUNDLE))
        ) as verified:
            for name, digest in hashes.items():
                if hashlib.sha256(verified.read(name)).hexdigest() != digest:
                    raise ValueError("Archive verification failed")
        size = sum(x.stat().st_size for x in directory.rglob("*") if x.is_file())
        index["videos"].append(
            {
                "manifest": v,
                "transcript": transcript,
                "ocr": ocr,
                "object_id": metadata["object_id"],
                "hashes": hashes,
                "source_bytes": size,
            }
        )
        source_bytes += size
        retained_bytes += metadata["bytes"]
    encoded = packed_json(index)
    if len(encoded) > MAX_INDEX:
        raise ValueError("Index exceeds storage limit")
    obj = blobs.ingest(io.BytesIO(encoded), MAX_INDEX)
    if gzip.decompress(blobs.read(obj["object_id"], MAX_INDEX)) != gzip.decompress(
        encoded
    ):
        raise ValueError("Index verification failed")
    pointer = root / "index.ref"
    temp = root / "index.ref.tmp"
    temp.write_text(obj["object_id"] + "\n")
    temp.chmod(0o600)
    temp.replace(pointer)
    report = {
        "videos": len(index["videos"]),
        "source_bytes": source_bytes,
        "retained_bytes": retained_bytes + len(encoded),
        "verified": True,
        "format": "original MP4 + deflated metadata, AES-GCM encrypted chunks",
        "images": "regenerated on demand in private tmpfs",
    }
    write_json(root / "storage-report.json", report)
    return report


class Archive:
    def __init__(self, policy, root=DEFAULT_ARCHIVE, key=None):
        self.policy = policy
        self.root = Path(root)
        self.blobs = BlobStore(
            self.root / "objects", key if key is not None else key_bytes()
        )
        ref = (self.root / "index.ref").read_text().strip()
        with gzip.GzipFile(
            fileobj=io.BytesIO(self.blobs.read(ref, MAX_INDEX))
        ) as stream:
            data = stream.read(MAX_INDEX + 1)
        if len(data) > MAX_INDEX:
            raise ValueError("Expanded index too large")
        self.index = json.loads(data)
        if self.index["version"] != 1:
            raise ValueError("Unsupported archive")
        self.entries = {
            v["manifest"]["id"]: v
            for v in self.index["videos"]
            if v["manifest"]["id"] in policy.ids
        }

    def entry(self, code):
        if code not in self.policy.ids or code not in self.entries:
            raise ValueError("Video is not in the current Saved allowlist")
        item = self.entries[code]
        if self.policy.authorize(item["manifest"]["url"]) != code:
            raise ValueError("Archive source mismatch")
        return item

    def list_videos(self):
        return [
            self.entry(self.policy.authorize(url))["manifest"]
            for url in self.policy.urls
            if self.policy.authorize(url) in self.entries
        ]

    def search(self, query, limit=20):
        terms = re.findall(r"\w+", query.casefold())
        if not terms:
            return []
        results = []
        for v in self.list_videos():
            item = self.entry(v["id"])
            last = {}
            for s in item["transcript"]["segments"]:
                score = sum(t in s["text"].casefold() for t in terms)
                if score:
                    results.append(
                        {
                            **s,
                            "id": v["id"],
                            "url": v["url"],
                            "score": score,
                            "modality": "speech",
                        }
                    )
            for f in item["ocr"]["frames"]:
                score = sum(t in f["text"].casefold() for t in terms)
                asset = f.get("asset", 0)
                if score and last.get(asset) != f["text"]:
                    results.append(
                        {
                            "id": v["id"],
                            "url": v["url"],
                            "score": score,
                            "modality": "screen_text",
                            "asset": asset,
                            "start": f["time"],
                            "end": f["time"],
                            "text": f["text"],
                        }
                    )
                last[asset] = f["text"]
        return sorted(results, key=lambda s: (-s["score"], s["id"], s["start"]))[
            : max(1, min(limit, 100))
        ]

    @contextlib.contextmanager
    def materialize(self, code):
        item = self.entry(code)
        data = self.blobs.read(item["object_id"], MAX_BUNDLE)
        # /run/user is a per-user tmpfs: no decrypted persistent video cache.
        runtime = Path(
            os.environ.get("XDG_RUNTIME_DIR", "/run/user/" + str(os.getuid()))
        )
        with tempfile.TemporaryDirectory(
            prefix="saved-evidence-", dir=runtime
        ) as temporary:
            p = Pipeline(self.policy, temporary)
            directory = p.path(code)
            directory.mkdir(mode=0o700)
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                total = 0
                for info in bundle.infolist():
                    name = PurePosixPath(info.filename)
                    if (
                        len(name.parts) != 1
                        or name.is_absolute()
                        or info.filename not in item["hashes"]
                    ):
                        raise ValueError("Unsafe archive member")
                    total += info.file_size
                    if total > MAX_BUNDLE:
                        raise ValueError("Expanded archive too large")
                    content = bundle.read(info)
                    if (
                        hashlib.sha256(content).hexdigest()
                        != item["hashes"][info.filename]
                    ):
                        raise ValueError("Source checksum mismatch")
                    dest = directory / info.filename
                    dest.write_bytes(content)
                    dest.chmod(0o600)
            yield p


def prune_plaintext(p, archive):
    """Remove only dedicated processed-post directories after full verification."""
    directories = []
    removed_bytes = 0
    for v in p.list_videos():
        directory = p.path(v["id"])
        if not directory.exists() or v.get("status") != "complete":
            continue
        item = archive.entry(v["id"])
        for name, digest in item["hashes"].items():
            path = directory / name
            if (
                path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise ValueError("Plaintext changed since archive verification")
        with archive.materialize(v["id"]):
            pass  # authenticate bundle, member hashes and safe extraction
        if any(x.is_symlink() for x in directory.rglob("*")):
            raise ValueError("Refusing to prune symlinked files")
        removed_bytes += sum(
            x.stat().st_size for x in directory.rglob("*") if x.is_file()
        )
        directories.append(directory)
    for directory in directories:
        shutil.rmtree(directory)
    return {
        "removed_post_directories": len(directories),
        "removed_bytes": removed_bytes,
    }


if __name__ == "__main__":
    os.umask(0o077)
    p = Pipeline(SavedPolicy(DEFAULT_ALLOWLIST), DEFAULT_DATA)
    if "--prune-verified" in sys.argv:
        report = prune_plaintext(p, Archive(p.policy))
    else:
        report = build_archive(p, DEFAULT_ARCHIVE, key_bytes())
    write_json(
        DEFAULT_DATA
        / (
            "prune-verification.json"
            if "--prune-verified" in sys.argv
            else "storage-verification.json"
        ),
        report,
    )
    print(json.dumps(report, indent=2))
