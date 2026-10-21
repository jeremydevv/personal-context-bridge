"""Encrypted, content-bound Voice Memo analysis and passage retrieval."""

import json
import math
from datetime import datetime, timezone


def chunks(text, max_chars=4000):
    if not isinstance(text, str) or not 100 <= max_chars <= 32000:
        raise ValueError("invalid transcript chunking")
    return [
        {"part": i // max_chars, "offset": i, "text": text[i : i + max_chars]}
        for i in range(0, len(text), max_chars)
    ]


def _summary(value):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("title"), str)
        or not 1 <= len(value["title"].strip()) <= 200
        or not isinstance(value.get("summary"), str)
        or not 1 <= len(value["summary"].strip()) <= 4000
    ):
        raise ValueError("invalid generated Voice Memo title or summary")
    return {"title": value["title"].strip(), "summary": value["summary"].strip()}


def summarize_full(text, generate, max_chars=12000):
    """Map every source character, recursively reduce; never silently truncate."""
    if not text.strip():
        raise ValueError("transcript is empty")
    parts = chunks(text, max_chars)
    summaries = [
        _summary(
            generate(
                {"task": "voice_memo_chunk_v1", "part": p["part"], "text": p["text"]}
            )
        )
        for p in parts
    ]
    # Restrict each reduction input without discarding any child summaries.
    while len(summaries) > 1:
        reduced = []
        group = []
        length = 0
        for item in summaries:
            size = len(json.dumps(item, ensure_ascii=False))
            if group and length + size > max_chars:
                reduced.append(
                    _summary(generate({"task": "voice_memo_reduce_v1", "parts": group}))
                )
                group = []
                length = 0
            group.append(item)
            length += size
        if group:
            reduced.append(
                _summary(generate({"task": "voice_memo_reduce_v1", "parts": group}))
            )
        if len(reduced) >= len(summaries):
            raise ValueError(
                "summary reduction did not converge; reduce summary length"
            )
        summaries = reduced
    return dict(summaries[0], covered_chars=len(text), source_chunks=len(parts))


SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_analysis(
 id TEXT PRIMARY KEY, source_digest TEXT NOT NULL, transcript TEXT NOT NULL,
 segments TEXT NOT NULL, transcript_source TEXT NOT NULL,
 generated_title TEXT, summary TEXT, model TEXT, generated_at TEXT,
 embedding_model TEXT, processing_error TEXT);
CREATE TABLE IF NOT EXISTS voice_audio(
 id TEXT PRIMARY KEY, audio_sha256 TEXT NOT NULL, object_id TEXT NOT NULL,
 bytes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS voice_chunks(
 id TEXT NOT NULL, part INTEGER NOT NULL, source_digest TEXT NOT NULL,
 offset INTEGER NOT NULL, text TEXT NOT NULL, vector TEXT,
 PRIMARY KEY(id,part));
CREATE VIRTUAL TABLE IF NOT EXISTS voice_chunks_fts USING fts5(id UNINDEXED,part UNINDEXED,text);
"""


class VoiceArchive:
    def __init__(self, store):
        self.store = store
        self.db = store.db

    def _current(self, identifier):
        row = self.store.get("voice_memo", identifier)
        if row is None:
            raise ValueError("Voice Memo not found")
        row["digest"] = self.db.execute(
            "SELECT digest FROM records WHERE kind='voice_memo' AND id=?", (identifier,)
        ).fetchone()[0]
        return row

    def _analysis(self, row):
        return self.db.execute(
            "SELECT * FROM voice_analysis WHERE id=? AND source_digest=?",
            (row["id"], row["digest"]),
        ).fetchone()

    def index_record(self, row, text, segments, source):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("complete transcript required")
        with self.db:
            current = self._current(row["id"])
            if "digest" not in row:
                row = dict(row, digest=current["digest"])
            if current["digest"] != row["digest"]:
                raise ValueError("Voice Memo changed during analysis")
            old = self._analysis(current)
            if old and old["transcript"] == text:
                return False
            self.db.execute(
                "INSERT OR REPLACE INTO voice_analysis(id,source_digest,transcript,segments,transcript_source) VALUES(?,?,?,?,?)",
                (row["id"], row["digest"], text, json.dumps(segments), source),
            )
            self.db.execute("DELETE FROM voice_chunks WHERE id=?", (row["id"],))
            self.db.execute("DELETE FROM voice_chunks_fts WHERE id=?", (row["id"],))
            for part in chunks(text):
                self.db.execute(
                    "INSERT INTO voice_chunks(id,part,source_digest,offset,text) VALUES(?,?,?,?,?)",
                    (
                        row["id"],
                        part["part"],
                        row["digest"],
                        part["offset"],
                        part["text"],
                    ),
                )
                self.db.execute(
                    "INSERT INTO voice_chunks_fts(id,part,text) VALUES(?,?,?)",
                    (row["id"], part["part"], part["text"]),
                )
        return True

    def save_summary(self, row, value, model):
        value = _summary(value)
        with self.db:
            if self._current(row["id"])["digest"] != row["digest"]:
                raise ValueError("Voice Memo changed during summarization")
            self.db.execute(
                "UPDATE voice_analysis SET generated_title=?,summary=?,model=?,generated_at=?,processing_error=NULL WHERE id=? AND source_digest=?",
                (
                    value["title"],
                    value["summary"],
                    model,
                    datetime.now(timezone.utc).isoformat(),
                    row["id"],
                    row["digest"],
                ),
            )

    def record(self, identifier):
        row = self._current(identifier)
        analysis = self._analysis(row)
        result = dict(row)
        result.pop("digest", None)
        result["analysis"] = {"generated": False, "status": "pending"}
        if analysis:
            result["analysis"] = {
                "generated": bool(analysis["summary"]),
                "title": analysis["generated_title"],
                "summary": analysis["summary"],
                "model": analysis["model"],
                "generated_at": analysis["generated_at"],
                "transcript_source": analysis["transcript_source"],
                "embedding_model": analysis["embedding_model"],
                "processing_error": analysis["processing_error"],
            }
        # Full text is available via paginated transcript tools, not duplicate fields.
        result.pop("body", None)
        result["payload"] = dict(result["payload"])
        result["payload"].pop("segments", None)
        return result

    def transcript(self, identifier, offset=0, max_chars=20000):
        if (
            type(offset) is not int
            or offset < 0
            or type(max_chars) is not int
            or not 1 <= max_chars <= 50000
        ):
            raise ValueError("invalid transcript range")
        row = self._current(identifier)
        analysis = self._analysis(row)
        text = analysis["transcript"] if analysis else row["body"]
        if offset > len(text):
            raise ValueError("transcript offset exceeds length")
        end = min(len(text), offset + max_chars)
        return {
            "id": identifier,
            "text": text[offset:end],
            "offset": offset,
            "total_chars": len(text),
            "next_offset": end if end < len(text) else None,
            "eof": end == len(text),
            "status": "available"
            if text
            else row["payload"].get("transcript_status", "pending"),
            "transcript_source": analysis["transcript_source"]
            if analysis
            else row["payload"].get("transcript_source"),
            "last_synced_at": self.store.last_sync("voice_memo"),
        }

    def search(self, query, limit=20, mode="keyword", embed=None, start=None, end=None):
        import re

        if mode not in ("keyword", "semantic", "hybrid"):
            raise ValueError("invalid search mode")
        limit = min(max(int(limit), 1), 100)
        terms = re.findall(r"\w+", query, flags=re.UNICODE)[:32]
        rows = []
        if terms and mode != "semantic":
            expression = " OR ".join('"' + term + '"' for term in terms)
            rows = [
                dict(r)
                for r in self.db.execute(
                    """
                SELECT c.id,c.part,c.offset,c.text,r.title FROM voice_chunks_fts f
                JOIN voice_chunks c ON c.id=f.id AND c.part=f.part
                JOIN records r ON r.kind='voice_memo' AND r.id=c.id
                WHERE voice_chunks_fts MATCH ? AND r.deleted=0 AND c.source_digest=r.digest
                AND (? IS NULL OR (julianday(r.start)>=julianday(?) AND julianday(r.start)<julianday(?)))
                ORDER BY bm25(voice_chunks_fts) LIMIT ?""",
                    (expression, start, start, end, limit * 3),
                )
            ]
            # Include new native transcripts and source-title matches before indexing.
            indexed_ids = {r["id"] for r in rows}
            rows.extend(
                dict(r, part=None, offset=None, text=r["body"])
                for r in self.store.search(
                    query, "voice_memo", limit, start=start, end=end
                )
                if r["id"] not in indexed_ids
            )
        semantic = []
        if mode != "keyword":
            if embed is None:
                raise ValueError("local embedding model is not configured")
            vector = embed([query])[0]
            for r in self.db.execute("""SELECT c.*,r.title,a.embedding_model FROM voice_chunks c
                JOIN records r ON r.kind='voice_memo' AND r.id=c.id AND r.digest=c.source_digest
                JOIN voice_analysis a ON a.id=c.id AND a.source_digest=c.source_digest
                WHERE r.deleted=0 AND c.vector IS NOT NULL"""):
                if r["embedding_model"] != embed.model:
                    continue
                stored = json.loads(r["vector"])
                if len(stored) != len(vector):
                    continue
                denominator = math.sqrt(
                    sum(x * x for x in stored) * sum(x * x for x in vector)
                )
                score = (
                    sum(a * b for a, b in zip(stored, vector)) / denominator
                    if denominator
                    else 0
                )
                if score > 0:
                    semantic.append(dict(r, score=score))
            semantic.sort(key=lambda r: r["score"], reverse=True)
            semantic = semantic[: limit * 3]
        scores = {}
        found = {}
        for ranking in (rows, semantic):
            for rank, row in enumerate(ranking, 1):
                key = (row["id"], row["part"])
                found[key] = row
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        results = []
        for key in sorted(scores, key=scores.get, reverse=True)[:limit]:
            r = found[key]
            results.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "part": r["part"],
                    "offset": r["offset"],
                    "excerpt": r["text"][:500],
                    "rank_score": scores[key],
                }
            )
        return {
            "results": results,
            "mode": mode,
            "last_synced_at": self.store.last_sync("voice_memo"),
        }

    def status(self):
        total = self.db.execute(
            "SELECT count(*) FROM records WHERE kind='voice_memo' AND deleted=0"
        ).fetchone()[0]
        row = self.db.execute("""SELECT count(*),sum(a.summary IS NOT NULL),sum(a.embedding_model IS NOT NULL)
            FROM voice_analysis a JOIN records r ON r.kind='voice_memo' AND r.id=a.id
            AND r.digest=a.source_digest WHERE r.deleted=0""").fetchone()
        return {
            "last_synced_at": self.store.last_sync("voice_memo"),
            "archived_recordings": total,
            "indexed_transcripts": row[0],
            "generated_summaries": row[1] or 0,
            "embedded_recordings": row[2] or 0,
            "icloud_state": "Mac-local availability only; archive freshness does not prove iPhone or iCloud completeness",
        }
