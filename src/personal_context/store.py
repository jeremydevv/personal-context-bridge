from .canvas_resources import CANVAS_KINDS, COURSE_KINDS
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .identifiers import contact_identifiers, correspondence_identifiers


QUERY_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "about", "be", "been", "by", "can",
    "did", "do", "does", "find", "for", "from", "had", "has", "have", "how",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "our", "say", "said",
    "s", "show", "t", "tell", "that", "the", "this", "to", "us", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "with", "you", "your",
})


def _calendar_window(batch):
    """Explicit subrange authority; ordinary incomplete batches never remove data."""
    if "calendar_window" not in batch:
        return None
    value = batch["calendar_window"]
    scope = re.fullmatch(r"calendar:(.+):([0-9]{4})-([0-9]{4})", batch.get("scope", ""))
    if (batch.get("source") != "apple-pim" or batch.get("kind") != "calendar"
            or batch.get("complete") is not False or not scope
            or not 0 <= int(scope[3]) - int(scope[2]) <= 2
            or not isinstance(value, dict) or set(value) != {"start", "end"}):
        raise ValueError("invalid authoritative calendar window")
    try:
        start, end = (datetime.fromisoformat(value[k].replace("Z", "+00:00")) for k in ("start", "end"))
        if (start.tzinfo is None or end.tzinfo is None or not start < end
                or end - start > timedelta(days=1098)):
            raise ValueError("invalid window bounds")
        for record in batch["records"]:
            payload = record.get("payload", {})
            if payload.get("calendarId") != scope[1]:
                raise ValueError("record outside authoritative calendar")
            native_id, native_start = payload.get("id"), payload.get("startDate")
            if (not isinstance(native_id, str) or not native_id
                    or not isinstance(native_start, str) or not native_start
                    or record["start"] != native_start
                    or record["id"] != native_id + "|" + native_start):
                raise ValueError("inconsistent calendar occurrence identity")
            if datetime.fromisoformat(record["start"].replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("calendar record requires an absolute start")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("invalid authoritative calendar window") from exc
    return start, end


def _calendar_quarantine(batch, path):
    # Optional private exact-ID/digest quarantine; never an unbounded title rule.
    if batch.get("source") != "apple-pim" or batch.get("kind") != "calendar" or not path.exists():
        return batch
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077 or path.stat().st_size > 262144:
        raise ValueError("calendar quarantine must be a private regular file")
    guard = json.loads(path.read_text())
    if (set(guard) != {"schema", "source", "kind", "scope", "expected_id_digest"}
            or guard["schema"] != 1 or guard["source"] != "apple-pim" or guard["kind"] != "calendar"
            or not isinstance(guard["scope"], str) or not re.fullmatch(r"calendar:.+:[0-9]{4}-[0-9]{4}", guard["scope"])
            or not isinstance(guard["expected_id_digest"], dict) or not 1 <= len(guard["expected_id_digest"]) <= 1000
            or any(not isinstance(k, str) or not k or not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                   for k, v in guard["expected_id_digest"].items())):
        raise ValueError("invalid exact calendar quarantine manifest")
    if batch["scope"] != guard["scope"]:
        return batch
    kept = []
    for item in batch["records"]:
        expected = guard["expected_id_digest"].get(item["id"])
        if expected is None:
            kept.append(item)
            continue
        snapshot = {k: batch[k] for k in ("source", "kind", "scope")}
        snapshot.update({"id": item["id"], "title": item["title"], "body": item.get("body", ""),
                         "start": item.get("start"), "end": item.get("end"), "payload": item.get("payload", {})})
        serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if hashlib.sha256(serialized.encode()).hexdigest() != expected:
            raise ValueError("quarantined calendar identity changed; review required")
    return dict(batch, records=kept)


class Store:
    def __init__(self, path, key_file=None, read_only=False):
        path = Path(path)
        self.path = path
        if read_only:
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError("existing archive required for read-only access")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        key_file = key_file or os.environ.get("PERSONAL_CONTEXT_KEY_FILE")
        if key_file:
            from sqlcipher3 import dbapi2 as driver
            key_path = Path(key_file)
            if key_path.is_symlink() or (key_path.stat().st_mode & 0o077):
                raise ValueError("encryption key file must not be a symlink and must be private")
            key = key_path.read_bytes()
            if len(key) != 32:
                raise ValueError("encryption key must contain exactly 32 bytes")
            self.db = (driver.connect(path.absolute().as_uri() + "?mode=ro", uri=True)
                       if read_only else driver.connect(str(path)))
            self.db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
            try:
                self.db.execute("SELECT count(*) FROM sqlite_master").fetchone()
            except Exception:
                self.db.close()
                raise
            if not read_only:
                path.chmod(0o600)
        else:
            driver = sqlite3
            self.db = (driver.connect(path.absolute().as_uri() + "?mode=ro", uri=True)
                       if read_only else driver.connect(str(path)))
        self.db.row_factory = driver.Row
        if read_only:
            self.db.execute("PRAGMA query_only=ON")
            return
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        had_index_meta = bool(self.db.execute("""
            SELECT 1 FROM sqlite_master WHERE type='table' AND name='derived_index_meta'
        """).fetchone())
        had_ready_row = bool(had_index_meta and self.db.execute("""
            SELECT 1 FROM derived_index_meta WHERE name='record_identifiers'
        """).fetchone())
        existing_records = bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'").fetchone()
                                and self.db.execute("SELECT 1 FROM records LIMIT 1").fetchone())
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                kind TEXT NOT NULL, id TEXT NOT NULL, source TEXT NOT NULL,
                scope TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                start TEXT, end TEXT, payload TEXT NOT NULL, digest TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0, captured_at TEXT NOT NULL,
                PRIMARY KEY (kind, id)
            );
            CREATE TABLE IF NOT EXISTS canvas_pdfs (
                record_id TEXT PRIMARY KEY, data BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS versions (
                version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL, id TEXT NOT NULL, captured_at TEXT NOT NULL,
                deleted INTEGER NOT NULL, snapshot TEXT
            );
            CREATE TABLE IF NOT EXISTS syncs (
                source TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL,
                collected_at TEXT NOT NULL, count INTEGER NOT NULL,
                PRIMARY KEY (source, kind, scope)
            );
            CREATE TABLE IF NOT EXISTS source_inventory (
                source TEXT NOT NULL, kind TEXT NOT NULL, source_id TEXT NOT NULL,
                first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                active INTEGER NOT NULL, PRIMARY KEY (source, kind, source_id)
            );
            CREATE TABLE IF NOT EXISTS inventory_scans (
                source TEXT NOT NULL, kind TEXT NOT NULL, collected_at TEXT NOT NULL,
                count INTEGER NOT NULL, added_count INTEGER NOT NULL,
                removed_count INTEGER NOT NULL, PRIMARY KEY (source, kind)
            );
            CREATE TABLE IF NOT EXISTS episode_parts (
                day TEXT NOT NULL, timezone TEXT NOT NULL, part INTEGER NOT NULL,
                source_digest TEXT NOT NULL, summary TEXT NOT NULL,
                citations TEXT NOT NULL, model TEXT NOT NULL,
                generated_at TEXT NOT NULL, source_count INTEGER NOT NULL,
                PRIMARY KEY (day, timezone, part)
            );
            CREATE TABLE IF NOT EXISTS image_attachments (
                guid TEXT PRIMARY KEY, object_id TEXT NOT NULL, mime_type TEXT NOT NULL,
                bytes INTEGER NOT NULL, source_mtime_ns INTEGER NOT NULL,
                sha256 TEXT NOT NULL, archived_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS archived_attachments (
                guid TEXT PRIMARY KEY, object_id TEXT NOT NULL, mime_type TEXT NOT NULL,
                bytes INTEGER NOT NULL, source_mtime_ns INTEGER NOT NULL,
                sha256 TEXT NOT NULL, archived_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
                kind UNINDEXED, id UNINDEXED, title, body
            );
            CREATE INDEX IF NOT EXISTS records_upcoming ON records(kind, deleted, start);
            CREATE INDEX IF NOT EXISTS records_timeline ON records(deleted, start);
            CREATE INDEX IF NOT EXISTS records_scope ON records(source, kind, scope, deleted, id, start);
            CREATE TABLE IF NOT EXISTS record_identifiers (
                kind TEXT NOT NULL, id TEXT NOT NULL, identifier TEXT NOT NULL,
                role TEXT NOT NULL, group_chat INTEGER NOT NULL,
                PRIMARY KEY (kind,id,identifier,role,group_chat)
            );
            CREATE INDEX IF NOT EXISTS record_identifiers_lookup
                ON record_identifiers(identifier,kind,id);
            CREATE TABLE IF NOT EXISTS derived_index_meta (
                name TEXT PRIMARY KEY, ready INTEGER NOT NULL
            );
        """)
        self.db.execute("INSERT OR IGNORE INTO derived_index_meta(name,ready) VALUES('record_identifiers',?)",
                        (0 if existing_records and not had_ready_row else 1,))
        self.db.execute("""
            INSERT OR IGNORE INTO archived_attachments
                (guid,object_id,mime_type,bytes,source_mtime_ns,sha256,archived_at)
            SELECT guid,object_id,mime_type,bytes,source_mtime_ns,sha256,archived_at
            FROM image_attachments
        """)
        from .voice_memos import SCHEMA as voice_schema
        self.db.executescript(voice_schema)
        self.db.commit()

    def close(self):
        self.db.close()

    @staticmethod
    def _canvas_window(batch):
        value = batch.get('canvas_window')
        if value is None:return None
        try:
            if batch['source'] != 'canvas-lms' or batch['kind'] not in ('canvas_planner_item','canvas_calendar_event') or batch['complete']:
                raise ValueError('unsupported Canvas window')
            if set(value) != {'start','end'}:raise ValueError('invalid Canvas window keys')
            start,end=(datetime.fromisoformat(value[k].replace('Z','+00:00')) for k in ('start','end'))
            if start.tzinfo is None or end.tzinfo is None or not start<end or end-start>timedelta(days=366):
                raise ValueError('invalid Canvas window bounds')
            for record in batch['records']:
                at=datetime.fromisoformat(record['start'].replace('Z','+00:00'))
                if at.tzinfo is None or not start<=at<end:raise ValueError('Canvas record outside window')
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            raise ValueError('invalid authoritative Canvas window') from exc
        return start,end

    @staticmethod
    def _validate(batch):
        if batch.get("schema") != 1 or batch.get("source") not in ("apple-pim", "apple-local", "canvas-lms"):
            raise ValueError("unsupported batch schema or source")
        if batch.get("kind") not in ("calendar", "reminder", "contact", "mail", "message", "note", "voice_memo", "inventory", *CANVAS_KINDS):
            raise ValueError("unsupported record kind")
        if (batch["source"] == "canvas-lms") != (batch["kind"] in CANVAS_KINDS):
            raise ValueError("Canvas records require the Canvas source")
        if batch["kind"] == "inventory" and (batch["source"] != "apple-pim" or batch.get("scope") not in ("calendar", "reminder", "mail")):
            raise ValueError("unsupported source inventory")
        if batch["kind"] in ("message", "note", "voice_memo") and batch["source"] != "apple-local":
            raise ValueError("Messages, Notes and Voice Memos require the local Apple source")
        if not isinstance(batch.get("scope"), str) or not batch["scope"]:
            raise ValueError("scope required")
        if not isinstance(batch.get("collected_at"), str) or not batch["collected_at"]:
            raise ValueError("collection time required")
        try:
            timestamp = datetime.fromisoformat(batch["collected_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("collection time must be ISO-8601") from exc
        if timestamp.tzinfo is None:
            raise ValueError("collection time must include a timezone")
        if not isinstance(batch.get("complete"), bool):
            raise ValueError("complete must be a boolean")
        records = batch.get("records")
        if not isinstance(records, list):
            raise ValueError("records must be a list")
        ids = set()
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
                raise ValueError("record ID required")
            if record["id"] in ids:
                raise ValueError("duplicate record ID")
            ids.add(record["id"])
            if not isinstance(record.get("title"), str) or not isinstance(record.get("body", ""), str):
                raise ValueError("record title and body must be strings")
            if not isinstance(record.get("payload", {}), dict):
                raise ValueError("payload must be an object")
        _calendar_window(batch)
        Store._canvas_window(batch)

    def ingest(self, batch):
        self._validate(batch)
        batch = _calendar_quarantine(batch, self.path.parent / "calendar-quarantine.json")
        if batch["kind"] == "inventory":
            return self._ingest_inventory(batch)
        kind, source, scope, timestamp = (batch[key] for key in ("kind", "source", "scope", "collected_at"))
        window = _calendar_window(batch) or self._canvas_window(batch)
        incoming = set()
        with self.db:
            prior = self.db.execute("""
                SELECT collected_at FROM syncs WHERE source=? AND kind=? AND scope=?
            """, (source, kind, scope)).fetchone()
            if prior and datetime.fromisoformat(timestamp.replace("Z", "+00:00")) < datetime.fromisoformat(prior[0].replace("Z", "+00:00")):
                return
            for item in batch["records"]:
                record_id = item["id"]
                incoming.add(record_id)
                if kind == "voice_memo" and not item.get("body", "").strip() and not item.get("payload", {}).get("audio_sha256"):
                    # iCloud can evict the local audio. Keep archived text explicitly
                    # historical instead of replacing a full transcript with empty text.
                    previous = self.get(kind, record_id)
                    if previous:
                        analysis = self.db.execute("""
                            SELECT a.transcript,a.segments,a.transcript_source
                            FROM voice_analysis a JOIN records r ON r.id=a.id
                            AND r.kind='voice_memo' AND r.digest=a.source_digest WHERE a.id=?
                        """, (record_id,)).fetchone()
                        text = analysis["transcript"] if analysis else previous["body"]
                        if text:
                            item = dict(item, body=text, payload=dict(item.get("payload", {})))
                            for field in ("audio_sha256", "audio_bytes"):
                                item["payload"][field] = previous["payload"].get(field)
                            item["payload"]["segments"] = json.loads(analysis["segments"]) if analysis else previous["payload"].get("segments", [])
                            item["payload"]["transcript_source"] = analysis["transcript_source"] if analysis else previous["payload"].get("transcript_source")
                            item["payload"]["transcript_status"] = "archived_previous_local_copy"
                            item["payload"]["transcript_currentness"] = "unverified_after_local_eviction"
                if kind == "canvas_file":
                    encoded = item.get("pdf_base64")
                    if encoded is None:
                        self.db.execute("DELETE FROM canvas_pdfs WHERE record_id=?", (record_id,))
                    else:
                        from .canvas_pdf import MAX_FILE_BYTES
                        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_FILE_BYTES + 2) // 3):
                            raise ValueError("Canvas PDF exceeds size limit")
                        data = base64.b64decode(encoded, validate=True)
                        if len(data) > MAX_FILE_BYTES or not data.startswith(b"%PDF-"):
                            raise ValueError("invalid Canvas PDF")
                        self.db.execute("INSERT OR REPLACE INTO canvas_pdfs(record_id,data) VALUES(?,?)",
                                        (record_id, data))
                snapshot = {
                    "id": record_id, "kind": kind, "source": source, "scope": scope,
                    "title": item["title"], "body": item.get("body", ""),
                    "start": item.get("start"), "end": item.get("end"),
                    "payload": item.get("payload", {}),
                }
                serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                digest = hashlib.sha256(serialized.encode()).hexdigest()
                old = self.db.execute("SELECT digest,deleted,title,body FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
                if old and old["digest"] == digest and not old["deleted"]:
                    continue
                self.db.execute("""
                    INSERT INTO records(kind,id,source,scope,title,body,start,end,payload,digest,deleted,captured_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,0,?)
                    ON CONFLICT(kind,id) DO UPDATE SET
                        source=excluded.source,scope=excluded.scope,title=excluded.title,
                        body=excluded.body,start=excluded.start,end=excluded.end,
                        payload=excluded.payload,digest=excluded.digest,deleted=0,captured_at=excluded.captured_at
                """, (kind, record_id, source, scope, item["title"], item.get("body", ""),
                      item.get("start"), item.get("end"), json.dumps(item.get("payload", {}), ensure_ascii=False), digest, timestamp))
                self.db.execute("INSERT INTO versions(kind,id,captured_at,deleted,snapshot) VALUES(?,?,?,0,?)",
                                (kind, record_id, timestamp, serialized))
                if (not old or old["deleted"] or old["title"] != item["title"]
                        or old["body"] != item.get("body", "")):
                    if old and not old["deleted"]:
                        self.db.execute("DELETE FROM records_fts WHERE kind=? AND id=?", (kind, record_id))
                    self.db.execute("INSERT INTO records_fts(kind,id,title,body) VALUES(?,?,?,?)",
                                    (kind, record_id, item["title"], item.get("body", "")))
                if kind in ("mail", "message"):
                    self.db.execute("DELETE FROM record_identifiers WHERE kind=? AND id=?", (kind, record_id))
                    self.db.executemany("""
                        INSERT INTO record_identifiers(kind,id,identifier,role,group_chat)
                        VALUES(?,?,?,?,?)
                    """, ((kind, record_id, identifier, role, int(group))
                          for identifier, role, group in correspondence_identifiers(kind, item.get("payload", {}))))
            if batch["complete"] or window is not None:
                existing = self.db.execute("SELECT id,start FROM records WHERE source=? AND kind=? AND scope=? AND deleted=0",
                                           (source, kind, scope)).fetchall()
                retired_ids = []
                for row in existing:
                    if row["id"] in incoming:
                        continue
                    if window is not None:
                        try:
                            start = datetime.fromisoformat(row["start"].replace("Z", "+00:00"))
                            if start.tzinfo is None or not window[0] <= start < window[1]:
                                continue
                        except (AttributeError, TypeError, ValueError):
                            # Unknown or malformed old dates cannot establish range membership.
                            continue
                    self.db.execute("UPDATE records SET deleted=1,captured_at=? WHERE kind=? AND id=?",
                                    (timestamp, kind, row["id"]))
                    self.db.execute("INSERT INTO versions(kind,id,captured_at,deleted,snapshot) VALUES(?,?,?,1,NULL)",
                                    (kind, row["id"], timestamp))
                    retired_ids.append(row["id"])
                    if kind in ("mail", "message"):
                        self.db.execute("DELETE FROM record_identifiers WHERE kind=? AND id=?", (kind, row["id"]))
                # kind/id are unindexed FTS columns. Group removals so a scope
                # retirement scans search content once per bounded chunk.
                for offset in range(0, len(retired_ids), 500):
                    chunk = retired_ids[offset:offset + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    self.db.execute("DELETE FROM records_fts WHERE kind=? AND id IN (" + placeholders + ")",
                                    (kind, *chunk))
                if kind == "canvas_course":
                    # Course removal also retires its assignments, announcements and files.
                    prefix = scope + ":course:"
                    for linked_kind in ("canvas_assignment", "canvas_announcement", "canvas_file", "canvas_module", "canvas_module_item", "canvas_page", *("canvas_" + k for k in COURSE_KINDS), "canvas_collection_state"):
                        retired_scopes = set()
                        for linked in self.db.execute("""
                        SELECT id,scope FROM records WHERE source='canvas-lms'
                        AND kind=? AND deleted=0
                    """, (linked_kind,)).fetchall():
                            linked_scope = linked["scope"]
                            if not linked_scope.startswith(prefix):
                                continue
                            course_id = linked_scope[len(prefix):]
                            if "canvas:" + scope + ":course:" + course_id in incoming:
                                continue
                            retired_scopes.add(linked_scope)
                            self.db.execute("UPDATE records SET deleted=1,captured_at=? WHERE kind=? AND id=?",
                                            (timestamp, linked_kind, linked["id"]))
                            self.db.execute("INSERT INTO versions(kind,id,captured_at,deleted,snapshot) VALUES(?,?,?,1,NULL)",
                                            (linked_kind, linked["id"], timestamp))
                            self.db.execute("DELETE FROM records_fts WHERE kind=? AND id=?",
                                            (linked_kind, linked["id"]))
                        for retired_scope in retired_scopes:
                            self.db.execute("""
                            INSERT INTO syncs(source,kind,scope,collected_at,count)
                            VALUES('canvas-lms',?,?,?,0)
                            ON CONFLICT(source,kind,scope) DO UPDATE SET
                                collected_at=excluded.collected_at,count=0
                        """, (linked_kind, retired_scope, timestamp))
            self.db.execute("""
                INSERT INTO syncs(source,kind,scope,collected_at,count) VALUES(?,?,?,?,?)
                ON CONFLICT(source,kind,scope) DO UPDATE SET collected_at=excluded.collected_at,count=excluded.count
            """, (source, kind, scope, timestamp, len(batch["records"])))

    def rebuild_record_identifiers(self):
        """Rebuild the derived index in one transaction; a failure rolls back all changes."""
        with self.db:
            self.db.execute("UPDATE derived_index_meta SET ready=0 WHERE name='record_identifiers'")
            self.db.execute("DELETE FROM record_identifiers")
            for row in self.db.execute("""
                SELECT kind,id,payload FROM records
                WHERE kind IN ('mail','message') AND deleted=0
            """):
                self.db.executemany("""
                    INSERT INTO record_identifiers(kind,id,identifier,role,group_chat)
                    VALUES(?,?,?,?,?)
                """, ((row["kind"], row["id"], identifier, role, int(group))
                      for identifier, role, group in correspondence_identifiers(row["kind"], json.loads(row["payload"]))))
            self.db.execute("UPDATE derived_index_meta SET ready=1 WHERE name='record_identifiers'")

    def contact_activity(self, contact_id, start, end, limit=50):
        ready = self.db.execute("SELECT ready FROM derived_index_meta WHERE name='record_identifiers'").fetchone()
        if not ready or not ready[0]:
            raise RuntimeError("contact activity index requires rebuild")
        contact = self.get("contact", contact_id)
        if not contact:
            raise ValueError("active Contact ID not found")
        identifiers = contact_identifiers(contact["payload"])
        ambiguous = set()
        for row in self.db.execute("SELECT id,payload FROM records WHERE kind='contact' AND deleted=0 AND id<>?", (contact_id,)):
            ambiguous.update(identifiers & contact_identifiers(json.loads(row["payload"])))
        usable = sorted(identifiers - ambiguous)
        results = {}
        for identifier in usable:
            for row in self.db.execute("""
                SELECT r.kind,r.id,r.start,ri.role,ri.group_chat
                FROM record_identifiers ri JOIN records r ON r.kind=ri.kind AND r.id=ri.id
                WHERE ri.identifier=? AND r.deleted=0 AND r.start>=? AND r.start<?
                ORDER BY r.start DESC LIMIT ?
            """, (identifier, start, end, limit)):
                key = (row["kind"], row["id"])
                item = results.setdefault(key, {"kind": row["kind"], "id": row["id"],
                                                "start": row["start"], "roles": set(), "group_chat": False})
                item["roles"].add(row["role"])
                item["group_chat"] = item["group_chat"] or bool(row["group_chat"])
        ordered = sorted(results.values(), key=lambda item: (item["start"], item["kind"], item["id"]), reverse=True)[:limit]
        for item in ordered:
            item["roles"] = sorted(item["roles"])
        return {"contact_id": contact_id, "ambiguous_identifiers": sorted(ambiguous),
                "last_synced_at": {kind: self.last_sync(kind) for kind in ("contact", "mail", "message")},
                "results": ordered}

    def _ingest_inventory(self, batch):
        if not batch["complete"]:
            raise ValueError("source inventory must be complete")
        source, kind, timestamp = batch["source"], batch["scope"], batch["collected_at"]
        incoming = {record["id"] for record in batch["records"]}
        with self.db:
            previous = self.db.execute("""
                SELECT collected_at FROM inventory_scans WHERE source=? AND kind=?
            """, (source, kind)).fetchone()
            if previous and datetime.fromisoformat(timestamp.replace("Z", "+00:00")) < datetime.fromisoformat(previous[0].replace("Z", "+00:00")):
                return
            old = {row["source_id"]: row["active"] for row in self.db.execute("""
                SELECT source_id,active FROM source_inventory WHERE source=? AND kind=?
            """, (source, kind))}
            added = sum(identifier not in old or not old[identifier] for identifier in incoming) if previous else 0
            removed = sum(bool(active) and identifier not in incoming for identifier, active in old.items())
            for identifier in incoming:
                self.db.execute("""
                    INSERT INTO source_inventory(source,kind,source_id,first_seen_at,last_seen_at,active)
                    VALUES(?,?,?,?,?,1) ON CONFLICT(source,kind,source_id) DO UPDATE SET
                        last_seen_at=excluded.last_seen_at,active=1
                """, (source, kind, identifier, timestamp, timestamp))
            if old:
                for identifier in old.keys() - incoming:
                    self.db.execute("""
                        UPDATE source_inventory SET active=0 WHERE source=? AND kind=? AND source_id=?
                    """, (source, kind, identifier))
            self.db.execute("""
                INSERT INTO inventory_scans(source,kind,collected_at,count,added_count,removed_count)
                VALUES(?,?,?,?,?,?) ON CONFLICT(source,kind) DO UPDATE SET
                    collected_at=excluded.collected_at,count=excluded.count,
                    added_count=excluded.added_count,removed_count=excluded.removed_count
            """, (source, kind, timestamp, len(incoming), added, removed))

    def get(self, kind, record_id, include_deleted=False):
        row = self.db.execute("SELECT * FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        if not row or (row["deleted"] and not include_deleted):
            return None
        result = dict(row)
        result["deleted"] = bool(result["deleted"])
        result["payload"] = json.loads(result["payload"])
        result.pop("digest")
        return result

    def search(self, query, kind=None, limit=20, return_mode=False, start=None, end=None):
        terms = [term for term in re.findall(r"[\w]+", query, flags=re.UNICODE)
                 if term.casefold() not in QUERY_STOPWORDS][:12]
        if not terms:
            return ([], "no_terms") if return_mode else []
        quoted = ['"' + term + '"' for term in terms]
        condition = ""
        if kind:
            condition = " AND r.kind=?"
        if start is not None:
            condition += " AND julianday(r.start)>=julianday(?) AND julianday(r.start)<julianday(?)"
        sql = """
            SELECT r.kind,r.id,r.title,r.body,r.start,r.end,r.scope,r.captured_at
            FROM records_fts f JOIN records r ON r.kind=f.kind AND r.id=f.id
            WHERE records_fts MATCH ? AND r.deleted=0
        """ + condition + " ORDER BY bm25(records_fts,0.0,0.0,3.0,1.0), r.start DESC LIMIT ?"
        def fetch(expression):
            params = [expression]
            if kind:
                params.append(kind)
            if start is not None:
                params.extend((start, end))
            params.append(min(max(int(limit), 1), 100))
            return [dict(row) for row in self.db.execute(sql, params).fetchall()]
        matches = fetch(" AND ".join(quoted))
        mode = "all_terms"
        if not matches and len(quoted) > 1:
            matches = fetch(" OR ".join(quoted))
            mode = "any_term"
        return (matches, mode) if return_mode else matches

    def upcoming(self, start, end, kind="calendar", limit=100):
        rows = self.db.execute("""
            SELECT kind,id,title,start,end,scope,captured_at FROM records
            WHERE kind=? AND deleted=0 AND start>=? AND start<? ORDER BY start LIMIT ?
        """, (kind, start, end, min(max(int(limit), 1), 200))).fetchall()
        return [dict(row) for row in rows]

    def open_reminders(self, limit=50, offset=0, include_items=False):
        limit = min(max(int(limit), 1), 200)
        offset = min(max(int(offset), 0), 10000)
        condition = "kind='reminder' AND deleted=0 AND json_extract(payload, '$.isCompleted')=0"
        total = self.db.execute("SELECT COUNT(*) FROM records WHERE " + condition).fetchone()[0]
        if not include_items:
            return total, []
        rows = self.db.execute("""
            SELECT kind,id,title,start,scope,captured_at FROM records
            WHERE """ + condition + """
            ORDER BY start IS NULL, start, title, id LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        return total, [dict(row) for row in rows]

    def timeline(self, start, end, kind=None, limit=50):
        params = [start, end]
        condition = ""
        if kind:
            condition = " AND kind=?"
            params.append(kind)
        params.append(min(max(int(limit), 1), 100))
        rows = self.db.execute("""
            SELECT kind,id,title,body,start,end,scope,captured_at FROM records
            WHERE deleted=0 AND start>=? AND start<?
        """ + condition + " ORDER BY start DESC,kind,id LIMIT ?", params).fetchall()
        return [dict(row) for row in rows]

    def last_sync(self, kind=None):
        if kind:
            row = self.db.execute("SELECT MAX(collected_at) FROM syncs WHERE kind=?", (kind,)).fetchone()
        else:
            row = self.db.execute("SELECT MAX(collected_at) FROM syncs").fetchone()
        return row[0]

    def version_count(self, kind, record_id):
        return self.db.execute("SELECT COUNT(*) FROM versions WHERE kind=? AND id=?", (kind, record_id)).fetchone()[0]

    def upsert_image_attachment(self, guid, object_id, mime_type, size, source_mtime_ns, sha256):
        if (not isinstance(guid, str) or not guid or len(guid) > 256
                or not isinstance(object_id, str) or not re.fullmatch(r"[0-9a-f]{64}", object_id)
                or not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256)
                or not isinstance(mime_type, str) or not mime_type.startswith("image/")
                or len(mime_type) > 128 or not isinstance(size, int) or size < 1
                or not isinstance(source_mtime_ns, int) or source_mtime_ns < 0):
            raise ValueError("invalid image attachment metadata")
        archived_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self.db:
            self.db.execute("""
                INSERT INTO image_attachments(guid,object_id,mime_type,bytes,source_mtime_ns,sha256,archived_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(guid) DO UPDATE SET
                    object_id=excluded.object_id,mime_type=excluded.mime_type,
                    bytes=excluded.bytes,source_mtime_ns=excluded.source_mtime_ns,
                    sha256=excluded.sha256,archived_at=excluded.archived_at
            """, (guid, object_id, mime_type, size, source_mtime_ns, sha256, archived_at))
        self.upsert_message_attachment(guid, object_id, mime_type, size, source_mtime_ns, sha256)

    def image_attachment(self, guid):
        row = self.db.execute("SELECT * FROM image_attachments WHERE guid=?", (guid,)).fetchone()
        return dict(row) if row else None

    def image_attachment_index(self):
        return [dict(row) for row in self.db.execute(
            "SELECT guid,bytes,source_mtime_ns,object_id FROM image_attachments ORDER BY guid")]

    def upsert_message_attachment(self, guid, object_id, mime_type, size, source_mtime_ns, sha256):
        if (not isinstance(guid, str) or not guid or len(guid) > 256
                or not isinstance(object_id, str) or not re.fullmatch(r"[0-9a-f]{64}", object_id)
                or not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256)
                or not isinstance(mime_type, str) or not mime_type or len(mime_type) > 128
                or not isinstance(size, int) or size < 1
                or not isinstance(source_mtime_ns, int) or source_mtime_ns < 0):
            raise ValueError("invalid Messages attachment metadata")
        archived_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self.db:
            self.db.execute("""
                INSERT INTO archived_attachments(guid,object_id,mime_type,bytes,source_mtime_ns,sha256,archived_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(guid) DO UPDATE SET
                    object_id=excluded.object_id,mime_type=excluded.mime_type,
                    bytes=excluded.bytes,source_mtime_ns=excluded.source_mtime_ns,
                    sha256=excluded.sha256,archived_at=excluded.archived_at
            """, (guid, object_id, mime_type, size, source_mtime_ns, sha256, archived_at))

    def message_attachment(self, guid):
        row = self.db.execute("SELECT * FROM archived_attachments WHERE guid=?", (guid,)).fetchone()
        return dict(row) if row else None

    def message_attachment_index(self):
        return [dict(row) for row in self.db.execute(
            "SELECT guid,bytes,source_mtime_ns,object_id FROM archived_attachments ORDER BY guid")]

    def episode_parts(self, day, timezone_name):
        rows = self.db.execute("""
            SELECT part,source_digest,summary,citations,model,generated_at,source_count
            FROM episode_parts WHERE day=? AND timezone=? ORDER BY part
        """, (day, timezone_name)).fetchall()
        return [{**dict(row), "citations": json.loads(row["citations"])} for row in rows]

    def replace_episode_parts(self, day, timezone_name, parts):
        with self.db:
            self.db.execute("DELETE FROM episode_parts WHERE day=? AND timezone=?", (day, timezone_name))
            for part in parts:
                self.db.execute("""
                    INSERT INTO episode_parts(day,timezone,part,source_digest,summary,
                                              citations,model,generated_at,source_count)
                    VALUES(?,?,?,?,?,?,?,?,?)
                """, (day, timezone_name, part["part"], part["source_digest"],
                      part["summary"], json.dumps(part["citations"]), part["model"],
                      part["generated_at"], part["source_count"]))

    def health(self, now=None, stale_after_hours=48):
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=stale_after_hours)).isoformat().replace("+00:00", "Z")
        sources = {}
        for kind in ("calendar", "reminder", "contact", "mail", "message", "note", "voice_memo", *CANVAS_KINDS):
            active = self.db.execute("SELECT COUNT(*) FROM records WHERE kind=? AND deleted=0", (kind,)).fetchone()[0]
            scopes, oldest, newest, stale = self.db.execute("""
                SELECT COUNT(*),MIN(collected_at),MAX(collected_at),
                       SUM(CASE WHEN collected_at < ? THEN 1 ELSE 0 END)
                FROM syncs WHERE kind=?
            """, (cutoff, kind)).fetchone()
            sources[kind] = {"active_records": active, "scopes": scopes,
                             "oldest_scope_sync": oldest, "last_sync": newest,
                             "stale_scopes": stale or 0}
            if kind in ("calendar", "reminder", "mail"):
                inventory = self.db.execute("""
                    SELECT collected_at,count,added_count,removed_count
                    FROM inventory_scans WHERE source='apple-pim' AND kind=?
                """, (kind,)).fetchone()
                missing = self.db.execute("""
                    SELECT COUNT(*) FROM source_inventory
                    WHERE source='apple-pim' AND kind=? AND active=0
                """, (kind,)).fetchone()[0]
                sources[kind]["inventory"] = ({"last_scan": inventory[0],
                    "current_sources": inventory[1], "added_last_scan": inventory[2],
                    "removed_last_scan": inventory[3], "missing_sources": missing}
                    if inventory else None)
        free_bytes = shutil.disk_usage(self.path.parent).free
        return {"checked_at": now.isoformat().replace("+00:00", "Z"),
                "stale_after_hours": stale_after_hours, "sources": sources,
                "storage": {"archive_bytes": self.path.stat().st_size,
                            "filesystem_free_bytes": free_bytes,
                            "low_space": free_bytes < 20 * 1024**3}}
