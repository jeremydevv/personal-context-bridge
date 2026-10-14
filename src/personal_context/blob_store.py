"""Bounded, authenticated storage for private binary attachments.

Blobs are streamed in encrypted chunks. A keyed content ID allows repeat
imports to share an object without exposing a plaintext hash in filenames.
"""

import hashlib
import hmac
import os
import re
import struct
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag


MAGIC = b"PCBLB001"
CHUNK_BYTES = 1024 * 1024
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
_ID = re.compile(r"[0-9a-f]{64}\Z")


class BlobStore:
    def __init__(self, root, key):
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("blob key must be 32 bytes")
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("blob root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.key = key
        self.cipher = AESGCM(hmac.digest(key, b"personal-context-blob-encryption-v1", "sha256"))

    def _path(self, object_id):
        if not isinstance(object_id, str) or not _ID.fullmatch(object_id):
            raise ValueError("invalid blob identifier")
        directory = self.root / object_id[:2]
        if directory.is_symlink():
            raise ValueError("blob directory cannot be a symlink")
        return directory / (object_id + ".blob")

    def ingest(self, stream, max_bytes=DEFAULT_MAX_BYTES):
        if not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("invalid blob size limit")
        digest = hashlib.sha256()
        total = 0
        index = 0
        fd, temporary = tempfile.mkstemp(prefix=".incoming-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(MAGIC)
                while True:
                    chunk = stream.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise ValueError("binary stream required")
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("blob exceeds size limit")
                    digest.update(chunk)
                    nonce = os.urandom(12)
                    aad = b"chunk" + struct.pack(">Q", index)
                    ciphertext = self.cipher.encrypt(nonce, chunk, aad)
                    output.write(struct.pack(">I", len(ciphertext)))
                    output.write(nonce)
                    output.write(ciphertext)
                    index += 1
                checksum = digest.digest()
                nonce = os.urandom(12)
                tag = self.cipher.encrypt(nonce, b"", b"end" + struct.pack(">Q", index) + checksum)
                output.write(struct.pack(">I", 0))
                output.write(checksum + nonce + tag)
                output.flush()
                os.fsync(output.fileno())
            object_id = hmac.digest(self.key, b"personal-context-blob-id-v1" + checksum, "sha256").hex()
            destination = self._path(object_id)
            destination.parent.mkdir(mode=0o700, exist_ok=True)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                pass
            return {"object_id": object_id, "sha256": checksum.hex(), "bytes": total}
        finally:
            Path(temporary).unlink(missing_ok=True)

    def read(self, object_id, max_bytes=DEFAULT_MAX_BYTES):
        if not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("invalid blob size limit")
        path = self._path(object_id)
        digest = hashlib.sha256()
        result = bytearray()
        index = 0
        try:
            with path.open("rb") as stream:
                if stream.read(len(MAGIC)) != MAGIC:
                    raise ValueError("invalid blob header")
                while True:
                    raw_length = stream.read(4)
                    if len(raw_length) != 4:
                        raise ValueError("truncated blob")
                    length = struct.unpack(">I", raw_length)[0]
                    if length == 0:
                        trailer = stream.read(60)
                        if len(trailer) != 60 or stream.read(1):
                            raise ValueError("invalid blob trailer")
                        checksum, nonce, tag = trailer[:32], trailer[32:44], trailer[44:]
                        self.cipher.decrypt(nonce, tag, b"end" + struct.pack(">Q", index) + checksum)
                        if digest.digest() != checksum:
                            raise ValueError("blob checksum mismatch")
                        expected = hmac.digest(self.key, b"personal-context-blob-id-v1" + checksum, "sha256").hex()
                        if expected != object_id:
                            raise ValueError("blob identifier mismatch")
                        return bytes(result)
                    if length <= 16 or length > CHUNK_BYTES + 16:
                        raise ValueError("invalid encrypted chunk size")
                    nonce = stream.read(12)
                    ciphertext = stream.read(length)
                    if len(nonce) != 12 or len(ciphertext) != length:
                        raise ValueError("truncated encrypted chunk")
                    chunk = self.cipher.decrypt(nonce, ciphertext, b"chunk" + struct.pack(">Q", index))
                    if len(result) + len(chunk) > max_bytes:
                        raise ValueError("blob exceeds read limit")
                    result.extend(chunk)
                    digest.update(chunk)
                    index += 1
        except InvalidTag as exc:
            raise ValueError("blob authentication failed") from exc

    def read_range(self, object_id, offset, length):
        """Return a small plaintext range after authenticating the whole blob."""
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid blob offset")
        if not isinstance(length, int) or not 1 <= length <= 256 * 1024:
            raise ValueError("invalid blob range length")
        path = self._path(object_id)
        digest = hashlib.sha256()
        result = bytearray()
        position = index = 0
        try:
            with path.open("rb") as stream:
                if stream.read(len(MAGIC)) != MAGIC:
                    raise ValueError("invalid blob header")
                while True:
                    raw_length = stream.read(4)
                    if len(raw_length) != 4:
                        raise ValueError("truncated blob")
                    encrypted_length = struct.unpack(">I", raw_length)[0]
                    if encrypted_length == 0:
                        trailer = stream.read(60)
                        if len(trailer) != 60 or stream.read(1):
                            raise ValueError("invalid blob trailer")
                        checksum, nonce, tag = trailer[:32], trailer[32:44], trailer[44:]
                        self.cipher.decrypt(nonce, tag, b"end" + struct.pack(">Q", index) + checksum)
                        if digest.digest() != checksum:
                            raise ValueError("blob checksum mismatch")
                        expected = hmac.digest(self.key, b"personal-context-blob-id-v1" + checksum, "sha256").hex()
                        if expected != object_id:
                            raise ValueError("blob identifier mismatch")
                        if offset > position:
                            raise ValueError("blob offset exceeds file size")
                        return bytes(result), position
                    if encrypted_length <= 16 or encrypted_length > CHUNK_BYTES + 16:
                        raise ValueError("invalid encrypted chunk size")
                    nonce = stream.read(12)
                    ciphertext = stream.read(encrypted_length)
                    if len(nonce) != 12 or len(ciphertext) != encrypted_length:
                        raise ValueError("truncated encrypted chunk")
                    chunk = self.cipher.decrypt(nonce, ciphertext, b"chunk" + struct.pack(">Q", index))
                    digest.update(chunk)
                    start = max(0, offset - position)
                    end = min(len(chunk), offset + length - position)
                    if start < end:
                        result.extend(chunk[start:end])
                    position += len(chunk)
                    index += 1
        except InvalidTag as exc:
            raise ValueError("blob authentication failed") from exc
