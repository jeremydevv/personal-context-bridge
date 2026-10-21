"""Read-only Voice Memos metadata and embedded Apple tsrp transcripts.

Apple's SQLite/MP4 formats are private and versioned by the OS. Unsupported
formats fail explicitly; no database repair, iCloud toggling or audio mutation.
"""

import hashlib
import json
import math
from pathlib import Path
import sqlite3
import struct
from datetime import datetime, timedelta, timezone

DEFAULT_RECORDINGS = (
    Path.home()
    / "Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
)
MAX_METADATA = 32 * 1024 * 1024
MAX_AUDIO = 1024 * 1024 * 1024


def _boxes(stream, lower, upper):
    offset = lower
    count = 0
    while offset < upper:
        count += 1
        if count > 100000:
            raise ValueError("too many MP4 atoms")
        if upper - offset < 8:
            raise ValueError("truncated MP4 atom")
        stream.seek(offset)
        size, kind = struct.unpack(">I4s", stream.read(8))
        header = 8
        if size == 1:
            raw = stream.read(8)
            if len(raw) != 8:
                raise ValueError("truncated extended MP4 atom")
            size = struct.unpack(">Q", raw)[0]
            header = 16
        elif size == 0:
            size = upper - offset
        if size < header or offset + size > upper:
            raise ValueError("invalid MP4 atom bounds")
        yield kind, offset + header, offset + size
        offset += size


def _runs(data):
    attributed = data.get("attributedString") if isinstance(data, dict) else None
    if not isinstance(attributed, dict):
        raise ValueError("unsupported Apple transcript format")
    runs = attributed.get("runs")
    attrs = attributed.get("attributeTable")
    if not isinstance(runs, list) or len(runs) % 2 or not isinstance(attrs, list):
        raise ValueError("invalid Apple transcript runs")
    segments = []
    for i in range(0, len(runs), 2):
        text, index = runs[i : i + 2]
        if (
            not isinstance(text, str)
            or type(index) is not int
            or not 0 <= index < len(attrs)
        ):
            raise ValueError("invalid Apple transcript attribute")
        timing = attrs[index].get("timeRange")
        start = end = None
        if timing is not None:
            if (
                not isinstance(timing, list)
                or len(timing) != 2
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) or v < 0
                    for v in timing
                )
            ):
                raise ValueError("invalid transcript timestamp")
            start, duration = timing
            end = start + duration
        segments.append({"text": text, "start": start, "end": end})
    return segments


def extract_transcript(path):
    """Seek around mdat; inspect bounded metadata, retaining every text run."""
    path = Path(path)
    with path.open("rb") as stream:
        size = path.stat().st_size
        leaves = []

        def walk(lower, upper, depth=0):
            if depth > 5:
                raise ValueError("excessive MP4 nesting")
            for kind, start, end in _boxes(stream, lower, upper):
                if kind == b"tsrp":
                    if end - start > MAX_METADATA:
                        raise ValueError("transcript metadata exceeds limit")
                    stream.seek(start)
                    raw = stream.read(end - start)
                    try:
                        leaves.append(_runs(json.loads(raw)))
                    except (UnicodeError, json.JSONDecodeError) as exc:
                        raise ValueError("invalid Apple transcript JSON") from exc
                elif kind in (b"moov", b"trak", b"udta"):
                    walk(start, end, depth + 1)

        walk(0, size)
    # Multi-track transcripts remain distinct rather than silently picking one.
    segments = []
    texts = []
    for index, leaf in enumerate(leaves):
        texts.append("".join(s["text"] for s in leaf))
        segments.extend(dict(s, track=index) for s in leaf)
    return {"text": "\n\n".join(texts), "segments": segments, "tracks": len(leaves)}


def _audio_path(root, raw):
    if not isinstance(raw, str) or not raw:
        return None, "not_downloaded"
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        path = candidate.resolve()
        if not path.is_relative_to(root.resolve()):
            return None, "path_rejected"
        if not path.is_file():
            return None, "not_downloaded"
        if path.suffix.lower() not in (".m4a", ".mp4", ".wav", ".caf"):
            return None, "unsupported_format"
        if not 0 < path.stat().st_size <= MAX_AUDIO:
            return None, "size_limit"
        return path, "available"
    except OSError:
        return None, "unavailable"


def collect_voice_memos(root=DEFAULT_RECORDINGS):
    root = Path(root)
    db = root / "CloudRecordings.db"
    if db.is_symlink() or not db.is_file():
        raise ValueError("Voice Memos database is unavailable")
    c = sqlite3.connect(db.absolute().as_uri() + "?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")
        cols = {r[1] for r in c.execute("PRAGMA table_info(ZCLOUDRECORDING)")}
        required = {"ZUNIQUEID", "ZCUSTOMLABEL", "ZDATE", "ZDURATION", "ZPATH"}
        if not required <= cols:
            raise ValueError("unsupported Voice Memos database schema")
        rows = c.execute("SELECT * FROM ZCLOUDRECORDING LIMIT 50001").fetchall()
        if len(rows) > 50000:
            raise ValueError("Voice Memos snapshot exceeds limit")
    finally:
        c.close()
    records = []
    available = missing = 0
    seen = set()
    for row in rows:
        row = dict(row)
        identifier = row["ZUNIQUEID"]
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("Voice Memos IDs are missing or duplicated")
        seen.add(identifier)
        path, status = _audio_path(root, row["ZPATH"])
        transcript = {"text": "", "segments": [], "tracks": 0}
        version = None
        size = 0
        mtime = 0
        transcript_status = "not_downloaded"
        if path:
            before = path.stat()
            size = before.st_size
            mtime = before.st_mtime_ns
            h = hashlib.sha256()
            with path.open("rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(block)
            version = h.hexdigest()
            try:
                transcript = extract_transcript(path)
                transcript_status = (
                    "available" if transcript["text"].strip() else "needs_transcription"
                )
            except ValueError:
                transcript_status = "unsupported_native_transcript"
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise RuntimeError(
                    "Voice Memo changed during collection; retry next run"
                )
        available += bool(transcript["text"])
        missing += not bool(transcript["text"])
        title = (
            row.get("ZCUSTOMLABELFORSORTING")
            or row["ZCUSTOMLABEL"]
            or "Untitled recording"
        )
        created = row["ZDATE"]
        duration = row["ZDURATION"]
        if type(created) not in (int, float) or not math.isfinite(created):
            raise ValueError("invalid Voice Memo date")
        if (
            type(duration) not in (int, float)
            or not math.isfinite(duration)
            or duration < 0
        ):
            raise ValueError("invalid Voice Memo duration")
        date = (
            (datetime(2001, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=created))
            .isoformat()
            .replace("+00:00", "Z")
        )
        records.append(
            {
                "id": identifier,
                "title": str(title),
                "body": transcript["text"],
                "start": date,
                "end": None,
                "payload": {
                    "original_title": str(title),
                    "duration_seconds": duration,
                    "segments": transcript["segments"],
                    "transcript_status": transcript_status,
                    "transcript_source": "apple-native" if transcript["text"] else None,
                    "audio_status": status,
                    "audio_sha256": version,
                    "audio_bytes": size,
                    "audio_mtime_ns": mtime,
                },
            }
        )
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # Additive snapshots: an empty/unhydrated iCloud cache never tombstones history.
    batches = [
        {
            "schema": 1,
            "source": "apple-local",
            "kind": "voice_memo",
            "scope": "voice-memos:all",
            "collected_at": timestamp,
            "complete": False,
            "records": records[i : i + 20],
        }
        for i in range(0, max(1, len(records)), 20)
    ]
    return batches, {
        "recordings": len(records),
        "native_transcripts": available,
        "missing_transcripts": missing,
    }


def audio_candidates(root=DEFAULT_RECORDINGS):
    root = Path(root)
    db = root / "CloudRecordings.db"
    c = sqlite3.connect(db.absolute().as_uri() + "?mode=ro", uri=True, timeout=30)
    try:
        items = []
        for identifier, raw in c.execute("SELECT ZUNIQUEID,ZPATH FROM ZCLOUDRECORDING"):
            path, _ = _audio_path(root, raw)
            if path:
                stat = path.stat()
                items.append(
                    {
                        "id": identifier,
                        "path": path,
                        "bytes": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                    }
                )
        return items
    finally:
        c.close()
