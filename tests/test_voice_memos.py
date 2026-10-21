import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from personal_context.voice_memos_collect import extract_transcript, collect_voice_memos
from personal_context.voice_memos import VoiceArchive, chunks, summarize_full
from personal_context.store import Store


def atom(name, data):
    return struct.pack(">I4s", len(data) + 8, name) + data


def audio(text="Fictional budget review. Final detail zebra."):
    runs = [text, 0]
    transcript = {
        "attributedString": {"runs": runs, "attributeTable": [{"timeRange": [0, 12]}]}
    }
    return (
        atom(b"ftyp", b"M4A ")
        + atom(b"mdat", b"fake")
        + atom(
            b"moov",
            atom(
                b"trak", atom(b"udta", atom(b"tsrp", json.dumps(transcript).encode()))
            ),
        )
    )


class VoiceTests(unittest.TestCase):
    def test_native_transcript_parses_entire_text_and_rejects_bad_atoms(self):
        text = "First. " + ("fictional words " * 6000) + "Last sentence."
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.m4a"
            p.write_bytes(audio(text))
            result = extract_transcript(p)
            self.assertEqual(result["text"], text)
            self.assertEqual(result["segments"][0]["end"], 12)
            p.write_bytes(struct.pack(">I4s", 2, b"moov"))
            with self.assertRaises(ValueError):
                extract_transcript(p)

    def test_collection_readonly_missing_audio_and_path_confinement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "CloudRecordings.db"
            c = sqlite3.connect(db)
            c.execute(
                "CREATE TABLE ZCLOUDRECORDING(ZUNIQUEID TEXT,ZCUSTOMLABEL TEXT,ZCUSTOMLABELFORSORTING TEXT,ZDATE REAL,ZDURATION REAL,ZPATH TEXT,ZFLAGS INTEGER)"
            )
            c.executemany(
                "INSERT INTO ZCLOUDRECORDING VALUES(?,?,?,?,?,?,?)",
                [
                    ("demo", "Internal", "Demo", 810000000, 12, "test.m4a", 0),
                    ("cloud", "Missing", "Cloud", 810000001, 15, "cloud.m4a", 0),
                    ("escape", "Escape", "Escape", 810000002, 15, "../outside.m4a", 0),
                ],
            )
            c.commit()
            c.close()
            (root / "test.m4a").write_bytes(audio())
            before = db.read_bytes()
            batches, counts = collect_voice_memos(root)
            rows = {r["id"]: r for b in batches for r in b["records"]}
            self.assertEqual(counts["recordings"], 3)
            self.assertEqual(rows["demo"]["title"], "Demo")
            self.assertIn("zebra", rows["demo"]["body"])
            self.assertEqual(rows["cloud"]["payload"]["audio_status"], "not_downloaded")
            self.assertEqual(rows["escape"]["payload"]["audio_status"], "path_rejected")
            self.assertEqual(before, db.read_bytes())
            self.assertTrue(all(not b["complete"] for b in batches))

    def test_chunks_and_summary_cover_end_without_truncation(self):
        text = ("fictional words " * 3000) + "UNIQUE END"
        parts = chunks(text, 1000)
        self.assertEqual("".join(p["text"] for p in parts), text)
        seen = []

        def generate(data):
            seen.append(data)
            return {"title": "Fictional review", "summary": "Budget discussed."}

        value = summarize_full(text, generate, max_chars=1000)
        self.assertEqual(value["title"], "Fictional review")
        self.assertTrue(any("UNIQUE END" in json.dumps(d) for d in seen))
        self.assertEqual(value["covered_chars"], len(text))

    def test_index_fulltext_pagination_stale_analysis_and_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp) / "archive.sqlite3")
            a = VoiceArchive(s)
            batch = {
                "schema": 1,
                "source": "apple-local",
                "kind": "voice_memo",
                "scope": "voice-memos:all",
                "collected_at": "2026-10-20T12:00:00Z",
                "complete": False,
                "records": [
                    {
                        "id": "demo",
                        "title": "Demo",
                        "body": "Fictional zebra ending.",
                        "start": "2026-10-20T11:00:00Z",
                        "payload": {"transcript_status": "available"},
                    }
                ],
            }
            s.ingest(batch)
            row = s.get("voice_memo", "demo")
            a.index_record(row, row["body"], [], "apple-native")
            self.assertEqual(a.search("zebra")["results"][0]["id"], "demo")
            self.assertEqual(
                a.transcript("demo", offset=10, max_chars=7)["text"], row["body"][10:17]
            )
            batch["collected_at"] = "2026-10-20T12:05:00Z"
            batch["records"][0]["body"] = "Changed orange."
            s.ingest(batch)
            self.assertEqual(a.search("zebra")["results"], [])
            self.assertEqual(a.transcript("demo")["text"], "Changed orange.")
            batch["complete"] = True
            batch["records"] = []
            batch["collected_at"] = "2026-10-20T12:10:00Z"
            s.ingest(batch)
            with self.assertRaises(ValueError):
                a.transcript("demo")
            s.close()

    def test_summary_failure_does_not_erase_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp) / "archive.sqlite3")
            a = VoiceArchive(s)
            s.ingest(
                {
                    "schema": 1,
                    "source": "apple-local",
                    "kind": "voice_memo",
                    "scope": "voice-memos:all",
                    "collected_at": "2026-10-20T12:00:00Z",
                    "complete": False,
                    "records": [
                        {
                            "id": "demo",
                            "title": "Demo",
                            "body": "A complete fictional transcript.",
                            "payload": {},
                        }
                    ],
                }
            )
            a.index_record(
                s.get("voice_memo", "demo"),
                "A complete fictional transcript.",
                [],
                "apple-native",
            )
            self.assertEqual(
                a.transcript("demo")["text"], "A complete fictional transcript."
            )
            self.assertFalse(a.record("demo")["analysis"]["generated"])
            s.close()


class VoiceWorkerTests(unittest.TestCase):
    def test_worker_replays_cached_analysis_and_semantic_model_scope(self):
        from personal_context.voice_memos_worker import process

        class Embed:
            model = "fictional-model-v1"

            def __call__(self, texts):
                return [[1.0, 0.0] if "budget" in t else [0.0, 1.0] for t in texts]

        class Summarizer:
            model = "fictional-summary-v1"
            calls = 0

            def __call__(self, data):
                self.calls += 1
                return {"title": "Budget review", "summary": "Fictional budget review."}

        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp) / "archive.sqlite3")
            a = VoiceArchive(s)
            s.ingest(
                {
                    "schema": 1,
                    "source": "apple-local",
                    "kind": "voice_memo",
                    "scope": "voice-memos:all",
                    "collected_at": "2026-10-20T12:00:00Z",
                    "complete": False,
                    "records": [
                        {
                            "id": "demo",
                            "title": "Demo",
                            "body": "Fictional budget plan.",
                            "payload": {},
                        }
                    ],
                }
            )
            generate = Summarizer()
            embed = Embed()
            result = process(s, generate, embed)
            self.assertEqual(result["indexed"], 1)
            self.assertEqual(result["summarized"], 1)
            self.assertEqual(result["embedded"], 1)
            self.assertEqual(process(s, generate, embed)["indexed"], 0)
            self.assertEqual(generate.calls, 1)
            self.assertEqual(
                a.search("budget", mode="hybrid", embed=embed)["results"][0]["id"],
                "demo",
            )
            embed.model = "different-model"
            self.assertEqual(
                a.search("budget", mode="semantic", embed=embed)["results"], []
            )
            self.assertEqual(a.record("demo")["title"], "Demo")
            self.assertEqual(a.record("demo")["analysis"]["title"], "Budget review")
            s.close()

    def test_worker_prioritizes_unindexed_records_over_pending_auth(self):
        from personal_context.voice_memos_worker import process

        class SignInRequired(Exception):
            pass

        class Pending:
            model = "fictional"

            def __call__(self, data):
                raise SignInRequired()

        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp) / "archive.sqlite3")
            s.ingest(
                {
                    "schema": 1,
                    "source": "apple-local",
                    "kind": "voice_memo",
                    "scope": "voice-memos:all",
                    "collected_at": "2026-10-20T12:00:00Z",
                    "complete": False,
                    "records": [
                        {
                            "id": str(i),
                            "title": "Demo",
                            "body": "Fictional text.",
                            "payload": {},
                        }
                        for i in range(3)
                    ],
                }
            )
            for _ in range(3):
                self.assertEqual(process(s, Pending(), limit=1)["indexed"], 1)
            self.assertEqual(
                s.db.execute("SELECT COUNT(*) FROM voice_analysis").fetchone()[0], 3
            )
            s.close()

    def test_worker_failure_and_edits_do_not_reuse_old_summary(self):
        from personal_context.voice_memos_worker import process

        class Failure:
            model = "fictional-model"

            def __call__(self, data):
                raise RuntimeError("fictional provider failure")

        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp) / "archive.sqlite3")
            a = VoiceArchive(s)
            s.ingest(
                {
                    "schema": 1,
                    "source": "apple-local",
                    "kind": "voice_memo",
                    "scope": "voice-memos:all",
                    "collected_at": "2026-10-20T12:00:00Z",
                    "complete": False,
                    "records": [
                        {
                            "id": "demo",
                            "title": "Demo",
                            "body": "Fictional complete text.",
                            "payload": {},
                        }
                    ],
                }
            )
            self.assertEqual(process(s, Failure())["errors"], ["RuntimeError"])
            self.assertIn("complete text", a.transcript("demo")["text"])
            self.assertFalse(a.record("demo")["analysis"]["generated"])
            self.assertEqual(
                a.record("demo")["analysis"]["processing_error"], "RuntimeError"
            )
            s.close()


class VoiceAudioTests(unittest.TestCase):
    def test_audio_ingest_verifies_digest_and_encrypts_original_bytes(self):
        import hashlib, os, subprocess, sys

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / "archive.key"
            key.write_bytes(os.urandom(32))
            key.chmod(0o600)
            data = audio()
            sha = hashlib.sha256(data).hexdigest()
            db = root / "context.sqlite3"
            s = Store(db, key_file=key)
            s.ingest(
                {
                    "schema": 1,
                    "source": "apple-local",
                    "kind": "voice_memo",
                    "scope": "voice-memos:all",
                    "collected_at": "2026-10-20T12:00:00Z",
                    "complete": False,
                    "records": [
                        {
                            "id": "demo",
                            "title": "Demo",
                            "body": "Fictional text.",
                            "payload": {
                                "audio_sha256": sha,
                                "audio_bytes": len(data),
                                "audio_mtime_ns": 1,
                            },
                        }
                    ],
                }
            )
            s.close()
            cmd = [
                sys.executable,
                "-m",
                "personal_context.cli",
                "voice-worker",
                "--db",
                str(db),
                "ingest-audio",
                "--record-id",
                "demo",
                "--sha256",
                sha,
                "--bytes",
                str(len(data)),
            ]
            env = dict(os.environ, PERSONAL_CONTEXT_KEY_FILE=str(key))
            result = subprocess.run(cmd, input=data, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            s = Store(db, key_file=key)
            r = s.db.execute("SELECT * FROM voice_audio").fetchone()
            from personal_context.blob_store import BlobStore

            blobs = BlobStore(root / "blobs", key.read_bytes())
            self.assertEqual(blobs.read(r["object_id"]), data)
            self.assertNotIn(
                b"Fictional", next((root / "blobs").rglob("*.blob")).read_bytes()
            )
            s.close()
            bad = data[:-1] + b"!"
            result = subprocess.run(cmd, input=bad, capture_output=True, env=env)
            self.assertNotEqual(result.returncode, 0)


class VoiceEvictionTests(unittest.TestCase):
    def test_icloud_eviction_retains_full_archived_text_as_historical(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp) / "archive.sqlite3")
            a = VoiceArchive(s)
            batch = {
                "schema": 1,
                "source": "apple-local",
                "kind": "voice_memo",
                "scope": "voice-memos:all",
                "collected_at": "2026-10-20T12:00:00Z",
                "complete": False,
                "records": [
                    {
                        "id": "demo",
                        "title": "Demo",
                        "body": "Complete fictional transcript.",
                        "payload": {
                            "audio_sha256": "a" * 64,
                            "audio_bytes": 42,
                            "transcript_source": "apple-native",
                        },
                    }
                ],
            }
            s.ingest(batch)
            a.index_record(
                s.get("voice_memo", "demo"),
                "Complete fictional transcript.",
                [],
                "apple-native",
            )
            batch["collected_at"] = "2026-10-20T12:05:00Z"
            batch["records"][0]["body"] = ""
            batch["records"][0]["payload"] = {
                "audio_status": "not_downloaded",
                "audio_sha256": None,
            }
            s.ingest(batch)
            self.assertEqual(
                a.transcript("demo")["text"], "Complete fictional transcript."
            )
            self.assertEqual(
                a.record("demo")["payload"]["transcript_currentness"],
                "unverified_after_local_eviction",
            )
            s.close()
