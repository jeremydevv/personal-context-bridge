"""Small, read-only operations exposed to AI clients."""

from datetime import date, datetime, timezone
from io import BytesIO
import base64
import os
import subprocess
from pathlib import Path

from .canvas_resources import CANVAS_KINDS

from .store import Store
from .settings import configured_timezone


def _utc_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    # The archive contains both whole-second and subsecond timestamps.
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class QueryService:
    def __init__(self, database_path):
        self.database_path = database_path

    def _use(self, operation):
        store = Store(self.database_path, read_only=True)
        try:
            return operation(store)
        finally:
            store.close()

    def search(self, query, kind=None, limit=20, start=None, end=None):
        if bool(start) != bool(end):
            raise ValueError("search start and end must be supplied together")
        if start:
            start, end = _utc_timestamp(start), _utc_timestamp(end)
            if start >= end:
                raise ValueError("search start must precede end")
        def run(store):
            from .voice_memos import VoiceArchive
            if kind == "voice_memo":
                return VoiceArchive(store).search(query, limit, start=start, end=end)
            rows, match_mode = store.search(query, kind, limit, return_mode=True,
                                            start=start, end=end)
            for row in rows:
                row["body"] = row["body"][:200]
            return {"last_synced_at": store.last_sync(kind),
                    "match_mode": match_mode,
                    "time_window": {"start": start, "end": end} if start else None,
                    "results": rows,
                    "voice_memo_results": VoiceArchive(store).search(query, limit, start=start, end=end)["results"] if kind is None else []}
        return self._use(run)

    def upcoming(self, start, end, kind="calendar", limit=100):
        start, end = _utc_timestamp(start), _utc_timestamp(end)
        if start >= end:
            raise ValueError("start must precede end")
        return self._use(lambda store: {
            "last_synced_at": store.last_sync(kind),
            "results": store.upcoming(start, end, kind, limit),
        })

    def open_reminders(self, limit=50, offset=0, include_items=False):
        def run(store):
            total, rows = store.open_reminders(limit, offset, include_items)
            return {"last_synced_at": store.last_sync("reminder"),
                    "total": total, "results": rows}
        return self._use(run)

    def timeline(self, start, end, kind=None, limit=50):
        start, end = _utc_timestamp(start), _utc_timestamp(end)
        if start >= end:
            raise ValueError("timeline start must precede end")
        if kind is not None and kind not in ("calendar", "reminder", "contact", "mail", "message", "note", "voice_memo", *CANVAS_KINDS):
            raise ValueError("invalid timeline kind")
        def run(store):
            rows = store.timeline(start, end, kind, limit)
            for row in rows:
                row["body"] = row["body"][:200]
            return {"last_synced_at": store.last_sync(kind), "results": rows}
        return self._use(run)

    def get(self, kind, record_id):
        if kind == "voice_memo":
            from .voice_memos import VoiceArchive
            return self._use(lambda store: {
                "last_synced_at": store.last_sync(kind),
                "record": VoiceArchive(store).record(record_id),
                "transcript": VoiceArchive(store).transcript(record_id),
            })
        return self._use(lambda store: {
            "last_synced_at": store.last_sync(kind),
            "record": store.get(kind, record_id),
        })

    def contact_activity(self, contact_id, start, end, limit=50):
        start, end = _utc_timestamp(start), _utc_timestamp(end)
        if start >= end:
            raise ValueError("start must precede end")
        if not isinstance(contact_id, str) or not contact_id:
            raise ValueError("exact Contact ID required")
        limit = min(max(int(limit), 1), 100)
        return self._use(lambda store: store.contact_activity(contact_id, start, end, limit))

    def message_attachment_info(self, guid):
        def run(store):
            row = store.message_attachment(guid)
            if row:
                row.pop("object_id", None)
                row.pop("sha256", None)
            return {"attachment": row, "message_last_synced_at": store.last_sync("message")}
        return self._use(run)

    def _attachment_bytes(self, guid, max_bytes):
        key_file = os.environ.get("PERSONAL_CONTEXT_KEY_FILE")
        if not key_file:
            raise RuntimeError("archive key is unavailable")
        from .blob_store import BlobStore
        store = Store(self.database_path, read_only=True)
        try:
            row = store.message_attachment(guid)
            if not row:
                raise ValueError("Messages attachment is not archived")
            if row["bytes"] > max_bytes:
                raise ValueError("Messages attachment exceeds this tool's read limit")
            key = Path(key_file).read_bytes()
            data = BlobStore(Path(self.database_path).parent / "blobs", key).read(
                row["object_id"], max_bytes=max_bytes)
            if len(data) != row["bytes"]:
                raise ValueError("archived attachment size mismatch")
            return row, data
        finally:
            store.close()

    def message_attachment_text(self, guid, max_chars=20000):
        max_chars = min(max(int(max_chars), 1), 20000)
        row, data = self._attachment_bytes(guid, 32 * 1024 * 1024)
        mime = row["mime_type"].split(";", 1)[0].lower()
        if mime == "application/pdf":
            extracted = subprocess.run(["pdftotext", "-", "-"], input=data,
                                       capture_output=True, timeout=30)
            if extracted.returncode:
                raise ValueError("PDF text extraction failed")
            content = extracted.stdout.decode("utf-8", errors="replace")
        elif (mime.startswith("text/") or mime in ("application/json", "application/xml",
                                                   "application/rtf", "application/x-rtf")):
            content = data.decode("utf-8", errors="replace")
        else:
            raise ValueError("attachment is not a supported text or PDF file")
        return {"guid": guid, "mime_type": mime, "text": content[:max_chars],
                "truncated": len(content) > max_chars, "archived_at": row["archived_at"]}

    def message_attachment_chunk(self, guid, offset=0, max_bytes=65536):
        """Read a bounded range of any archived Messages file as base64."""
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid attachment offset")
        max_bytes = min(max(int(max_bytes), 1), 256 * 1024)
        key_file = os.environ.get("PERSONAL_CONTEXT_KEY_FILE")
        if not key_file:
            raise RuntimeError("archive key is unavailable")
        from .blob_store import BlobStore
        store = Store(self.database_path, read_only=True)
        try:
            row = store.message_attachment(guid)
            if not row:
                raise ValueError("Messages attachment is not archived")
            if offset > row["bytes"]:
                raise ValueError("attachment offset exceeds file size")
            key = Path(key_file).read_bytes()
            chunk, total = BlobStore(Path(self.database_path).parent / "blobs", key).read_range(
                row["object_id"], offset, max_bytes)
            if total != row["bytes"]:
                raise ValueError("archived attachment size mismatch")
            return {"guid": guid, "mime_type": row["mime_type"], "bytes": total,
                    "offset": offset, "data_base64": base64.b64encode(chunk).decode("ascii"),
                    "next_offset": offset + len(chunk), "eof": offset + len(chunk) == total,
                    "archived_at": row["archived_at"]}
        finally:
            store.close()

    def message_image_preview(self, guid):
        row, data = self._attachment_bytes(guid, 64 * 1024 * 1024)
        if not row["mime_type"].lower().startswith("image/"):
            raise ValueError("attachment is not an image")
        from PIL import Image
        from pillow_heif import register_heif_opener
        register_heif_opener()
        with Image.open(BytesIO(data)) as original:
            original.thumbnail((2048, 2048))
            frame = original.convert("RGB")
            output = BytesIO()
            frame.save(output, format="JPEG", quality=85)
        return output.getvalue()

    def status(self):
        from .refresh_mcp import with_tracking
        result = self._use(lambda store: {
            "calendar_last_synced_at": store.last_sync("calendar"),
            "reminder_last_synced_at": store.last_sync("reminder"),
            "contact_last_synced_at": store.last_sync("contact"),
            "mail_last_synced_at": store.last_sync("mail"),
            "message_last_synced_at": store.last_sync("message"),
            "note_last_synced_at": store.last_sync("note"),
            "voice_memo_last_synced_at": store.last_sync("voice_memo"),
            "canvas_module_last_synced_at": store.last_sync("canvas_module"),
            "canvas_module_item_last_synced_at": store.last_sync("canvas_module_item"),
            "canvas_page_last_synced_at": store.last_sync("canvas_page"),
            "canvas_course_last_synced_at": store.last_sync("canvas_course"),
            "canvas_assignment_last_synced_at": store.last_sync("canvas_assignment"),
            "canvas_announcement_last_synced_at": store.last_sync("canvas_announcement"),
            "canvas_file_last_synced_at": store.last_sync("canvas_file"),
            "canvas_conversation_last_synced_at": store.last_sync("canvas_conversation"),
        })

        return with_tracking(result, database=self.database_path)

    def health(self):
        """Aggregate freshness and coverage without returning personal content."""
        return self._use(lambda store: store.health())

    def daily_summary(self, day, timezone_name=None):
        timezone_name = configured_timezone(timezone_name)
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("day must be YYYY-MM-DD")
        def run(store):
            parts = store.episode_parts(day, timezone_name)
            public = [{key: part[key] for key in ("part", "summary", "citations", "model",
                                                   "generated_at", "source_count")}
                      for part in parts]
            return {"day": day, "timezone": timezone_name, "generated_unverified": bool(parts),
                    "last_synced_at": store.last_sync(), "parts": public}
        return self._use(run)
