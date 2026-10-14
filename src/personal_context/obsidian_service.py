"""Bounded filesystem operations for the private Obsidian MCP app."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from uuid import uuid4


DEFAULT_VAULTS = ("Notes", "Projects", "Journal")
MAX_NOTE_BYTES = 1024 * 1024
MAX_BINARY_CHUNK = 65536
MAX_RESULTS = 100
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SYNC_STALE_AFTER_SECONDS = 30 * 60


class ObsidianVaultService:
    def __init__(self, root: str | Path, vaults=DEFAULT_VAULTS, *,
                 write_enabled: bool = False, require_mount: bool = True):
        self.root = Path(root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("vault root must be a directory")
        if require_mount and not os.path.ismount(self.root):
            raise RuntimeError("vault root is not mounted; refusing to use the underlying directory")
        if not vaults or any(not name or "/" in name or name in (".", "..") for name in vaults):
            raise ValueError("invalid vault allowlist")
        self.vaults = tuple(dict.fromkeys(vaults))
        self.write_enabled = write_enabled

    def _vault(self, vault: str) -> Path:
        if vault not in self.vaults:
            raise ValueError("vault is not allowed")
        path = self.root / vault
        if path.is_symlink() or not path.is_dir():
            raise FileNotFoundError("vault is unavailable")
        return path

    @staticmethod
    def _parts(relative_path: str) -> tuple[str, ...]:
        if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path or "\x00" in relative_path:
            raise ValueError("invalid path")
        parsed = PurePosixPath(relative_path)
        parts = relative_path.split("/")
        if parsed.is_absolute() or any(part in ("", ".", "..") for part in parts):
            raise ValueError("path must stay inside one vault")
        if parts[0] == ".mcp-backups":
            raise ValueError("backup area is not exposed")
        return tuple(parts)

    def _path(self, vault: str, relative_path: str, *, allow_missing: bool = False) -> Path:
        current = self._vault(vault)
        parts = self._parts(relative_path)
        for index, part in enumerate(parts):
            current = current / part
            if current.is_symlink():
                raise ValueError("symlinks are not allowed")
            if index < len(parts) - 1 and current.exists() and not current.is_dir():
                raise ValueError("parent is not a directory")
        if not allow_missing and not current.exists():
            raise FileNotFoundError("file not found")
        if current.exists() and not current.resolve(strict=True).is_relative_to(self._vault(vault)):
            raise ValueError("path escapes vault")
        return current

    def _check_write(self, relative_path: str) -> None:
        if not self.write_enabled:
            raise PermissionError("Obsidian writes are disabled")
        parts = self._parts(relative_path)
        if any(part.startswith(".") for part in parts) or not relative_path.lower().endswith(".md"):
            raise ValueError("writes are limited to non-hidden Markdown notes")

    @staticmethod
    def _digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _read_bounded(path: Path, cap: int) -> bytes:
        if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("path is not a regular file")
        if path.stat().st_size > cap:
            raise ValueError("file is too large for this tool")
        with path.open("rb") as file:
            data = file.read(cap + 1)
        if len(data) > cap:
            raise ValueError("file is too large for this tool")
        return data

    def list_vaults(self) -> dict:
        return {"vaults": [{"name": name, "available": (self.root / name).is_dir()}
                           for name in self.vaults], "write_enabled": self.write_enabled}

    def sync_status(self) -> dict:
        status_file = self.root / ".mcp-backups" / "sync_status.json"
        if not status_file.is_file():
            return {"last_success_at": None, "mode": None, "age_seconds": None,
                    "stale": True, "stale_after_seconds": SYNC_STALE_AFTER_SECONDS}
        data = json.loads(self._read_bounded(status_file, 4096).decode("utf-8"))
        last_success = data.get("last_success_at")
        age = None
        if isinstance(last_success, str):
            try:
                parsed = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    age = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
            except ValueError:
                pass
        return {"last_success_at": last_success, "mode": data.get("mode"),
                "age_seconds": age, "stale": age is None or age >= SYNC_STALE_AFTER_SECONDS,
                "stale_after_seconds": SYNC_STALE_AFTER_SECONDS}

    def list_files(self, vault: str, directory: str = "", limit: int = 100) -> dict:
        limit = max(1, min(int(limit), MAX_RESULTS))
        base = self._vault(vault) if not directory else self._path(vault, directory)
        if not base.is_dir():
            raise ValueError("directory is not a folder")
        rows = []
        for child in sorted(base.iterdir(), key=lambda path: path.name.casefold()):
            if child.name == ".mcp-backups" or child.is_symlink():
                continue
            rows.append({"path": child.relative_to(self._vault(vault)).as_posix(),
                         "directory": child.is_dir(),
                         "size": child.stat().st_size if child.is_file() else None})
            if len(rows) > limit:
                break
        return {"vault": vault, "directory": directory, "entries": rows[:limit],
                "truncated": len(rows) > limit}

    def read_note(self, vault: str, path: str) -> dict:
        if not path.lower().endswith(".md"):
            raise ValueError("read_note requires a Markdown note")
        file = self._path(vault, path)
        data = self._read_bounded(file, MAX_NOTE_BYTES)
        return {"vault": vault, "path": path, "content": data.decode("utf-8"),
                "sha256": self._digest(data), "size": len(data)}

    def read_attachment_chunk(self, vault: str, path: str, offset: int = 0,
                              max_bytes: int = MAX_BINARY_CHUNK) -> dict:
        file = self._path(vault, path)
        if not file.is_file():
            raise ValueError("path is not a file")
        offset = int(offset)
        if offset < 0:
            raise ValueError("offset must be nonnegative")
        max_bytes = max(1, min(int(max_bytes), MAX_BINARY_CHUNK))
        size = file.stat().st_size
        with file.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(max_bytes)
        return {"vault": vault, "path": path, "offset": offset, "size": size,
                "base64": base64.b64encode(data).decode("ascii"),
                "next_offset": offset + len(data), "eof": offset + len(data) >= size}

    def search_notes(self, query: str, vault: str = "", limit: int = 20) -> dict:
        query = query.strip()
        if not query or len(query) > 200:
            raise ValueError("query must contain 1-200 characters")
        limit = max(1, min(int(limit), 50))
        vault_names = (vault,) if vault else self.vaults
        results = []
        scanned = 0
        for name in vault_names:
            root = self._vault(name)
            for file in root.rglob("*.md"):
                if file.is_symlink() or any(part.startswith(".") for part in file.relative_to(root).parts):
                    continue
                scanned += 1
                try:
                    data = self._read_bounded(file, MAX_NOTE_BYTES)
                    content = data.decode("utf-8")
                except (OSError, UnicodeError, ValueError):
                    continue
                match = re.search(re.escape(query), content, re.IGNORECASE)
                if match:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    results.append({"vault": name, "path": file.relative_to(root).as_posix(),
                                    "snippet": content[start:end], "sha256": self._digest(data)})
                    if len(results) >= limit:
                        return {"results": results, "truncated": True, "scanned": scanned}
        return {"results": results, "truncated": False, "scanned": scanned}

    def _lock(self):
        lock_path = self.root / ".mcp-write.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor

    def _audit(self, action: str, vault: str, path: str, sha256: str | None) -> None:
        audit = self.root / ".mcp-backups" / "audit.jsonl"
        audit.parent.mkdir(mode=0o700, exist_ok=True)
        with os.fdopen(os.open(audit, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600), "w") as stream:
            stream.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                     "action": action, "vault": vault, "path": path,
                                     "sha256": sha256}, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _backup(self, file: Path, vault: str, path: str) -> Path:
        target_dir = self.root / ".mcp-backups" / vault
        target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = target_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex + ".md")
        shutil.copy2(file, target)
        os.chmod(target, 0o600)
        return target

    def write_note(self, vault: str, path: str, content: str,
                   expected_sha256: str = "") -> dict:
        self._check_write(path)
        if not isinstance(content, str):
            raise ValueError("content must be text")
        data = content.encode("utf-8")
        if len(data) > MAX_NOTE_BYTES:
            raise ValueError("note exceeds 1 MiB")
        if expected_sha256 and not SHA256_RE.fullmatch(expected_sha256):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
        descriptor = self._lock()
        try:
            file = self._path(vault, path, allow_missing=True)
            exists = file.exists()
            if exists:
                current = self._read_bounded(file, MAX_NOTE_BYTES)
                current_hash = self._digest(current)
                if expected_sha256 != current_hash:
                    raise ValueError("note changed; read it again before writing")
            elif expected_sha256:
                raise ValueError("note is missing; expected_sha256 must be empty to create")
            file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if exists:
                self._backup(file, vault, path)
            with tempfile.NamedTemporaryFile(dir=file.parent, prefix=".mcp-write-", delete=False) as tmp:
                temp_path = Path(tmp.name)
                os.chmod(temp_path, 0o600)
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            try:
                os.replace(temp_path, file)
            finally:
                temp_path.unlink(missing_ok=True)
            digest = self._digest(data)
            self._audit("write", vault, path, digest)
            return {"vault": vault, "path": path, "created": not exists,
                    "sha256": digest, "size": len(data)}
        finally:
            os.close(descriptor)

    def append_note(self, vault: str, path: str, text: str,
                    expected_sha256: str) -> dict:
        current = self.read_note(vault, path)
        if current["sha256"] != expected_sha256:
            raise ValueError("note changed; read it again before writing")
        return self.write_note(vault, path, current["content"] + text, expected_sha256)

    def replace_in_note(self, vault: str, path: str, old: str, new: str,
                        expected_sha256: str, replace_all: bool = False) -> dict:
        if not old:
            raise ValueError("old text must be nonempty")
        current = self.read_note(vault, path)
        if current["sha256"] != expected_sha256:
            raise ValueError("note changed; read it again before writing")
        count = current["content"].count(old)
        if count == 0:
            raise ValueError("old text not found")
        if count > 1 and not replace_all:
            raise ValueError("old text occurs more than once; choose replace_all")
        updated = current["content"].replace(old, new, -1 if replace_all else 1)
        result = self.write_note(vault, path, updated, expected_sha256)
        result["replacements"] = count if replace_all else 1
        return result

    def trash_note(self, vault: str, path: str, expected_sha256: str) -> dict:
        self._check_write(path)
        if not SHA256_RE.fullmatch(expected_sha256):
            raise ValueError("expected_sha256 is required")
        descriptor = self._lock()
        try:
            file = self._path(vault, path)
            current = self._read_bounded(file, MAX_NOTE_BYTES)
            if self._digest(current) != expected_sha256:
                raise ValueError("note changed; read it again before removing")
            target = self._backup(file, vault, path)
            file.unlink()
            self._audit("trash", vault, path, expected_sha256)
            return {"vault": vault, "path": path, "trashed": True,
                    "backup_id": target.name, "sha256": expected_sha256}
        finally:
            os.close(descriptor)
