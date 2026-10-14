"""Encrypted binary archive checks run where cryptography is installed."""

import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("cryptography"), "cryptography is server-only")
class BlobStoreTests(unittest.TestCase):
    def test_ingest_is_encrypted_deduplicated_and_readable(self):
        from personal_context.blob_store import BlobStore

        secret = b"personal image bytes " * 1200
        with tempfile.TemporaryDirectory() as directory:
            store = BlobStore(Path(directory), b"k" * 32)
            first = store.ingest(io.BytesIO(secret))
            second = store.ingest(io.BytesIO(secret))
            self.assertEqual(first, second)
            self.assertEqual(hashlib.sha256(secret).hexdigest(), first["sha256"])
            self.assertEqual(len(secret), first["bytes"])
            self.assertEqual(secret, store.read(first["object_id"]))
            files = list(Path(directory).rglob("*.blob"))
            self.assertEqual(1, len(files))
            self.assertNotIn(secret[:100], files[0].read_bytes())
            self.assertEqual(0o600, files[0].stat().st_mode & 0o777)

    def test_tampered_blob_fails_authentication(self):
        from personal_context.blob_store import BlobStore

        with tempfile.TemporaryDirectory() as directory:
            store = BlobStore(Path(directory), b"k" * 32)
            result = store.ingest(io.BytesIO(b"private image data"))
            path = next(Path(directory).rglob("*.blob"))
            data = bytearray(path.read_bytes())
            data[-17] ^= 1
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                store.read(result["object_id"])

    def test_oversize_upload_leaves_no_blob(self):
        from personal_context.blob_store import BlobStore

        with tempfile.TemporaryDirectory() as directory:
            store = BlobStore(Path(directory), b"k" * 32)
            with self.assertRaises(ValueError):
                store.ingest(io.BytesIO(b"too large"), max_bytes=4)
            self.assertEqual([], list(Path(directory).rglob("*.blob")))

    def test_read_range_across_chunks_and_rejects_tampering(self):
        from personal_context.blob_store import BlobStore, CHUNK_BYTES

        payload = b"a" * (CHUNK_BYTES - 3) + b"crossing" + b"z" * 20
        with tempfile.TemporaryDirectory() as directory:
            store = BlobStore(Path(directory), b"k" * 32)
            item = store.ingest(io.BytesIO(payload))
            chunk, total = store.read_range(item["object_id"], CHUNK_BYTES - 5, 12)
            self.assertEqual(payload[CHUNK_BYTES - 5:CHUNK_BYTES + 7], chunk)
            self.assertEqual(len(payload), total)
            self.assertEqual((b"", len(payload)), store.read_range(item["object_id"], len(payload), 1))
            with self.assertRaises(ValueError):
                store.read_range(item["object_id"], len(payload) + 1, 1)
            with self.assertRaises(ValueError):
                store.read_range(item["object_id"], 0, 256 * 1024 + 1)
            path = next(Path(directory).rglob("*.blob"))
            raw = bytearray(path.read_bytes())
            raw[-17] ^= 1
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                store.read_range(item["object_id"], 0, 8)


if __name__ == "__main__":
    unittest.main()
