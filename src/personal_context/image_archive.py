"""Discover local Messages images without reading outside its attachment tree."""

import mimetypes
import sqlite3
from pathlib import Path


DEFAULT_MESSAGES_DB = Path.home() / "Library/Messages/chat.db"
DEFAULT_ATTACHMENTS = Path.home() / "Library/Messages/Attachments"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif",
                  ".webp", ".tif", ".tiff", ".bmp"}
MAX_IMAGE_BYTES = 1024 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024 * 1024


def collect_attachment_candidates(db_path=DEFAULT_MESSAGES_DB,
                                  attachments_root=DEFAULT_ATTACHMENTS,
                                  max_bytes=MAX_ATTACHMENT_BYTES):
    """Return available Messages attachment files from a read-only snapshot."""
    db_path = Path(db_path)
    if not db_path.is_file() or db_path.is_symlink():
        raise ValueError("Messages database is unavailable")
    root = Path(attachments_root).resolve(strict=True)
    allowed_roots = [root]
    stickers = root.parent / "StickerCache"
    if stickers.is_dir() and not stickers.is_symlink():
        allowed_roots.append(stickers.resolve(strict=True))
    connection = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    found = {}
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        for row in connection.execute("""
            SELECT DISTINCT a.guid, a.filename, a.mime_type
            FROM attachment a JOIN message_attachment_join maj ON maj.attachment_id=a.ROWID
            WHERE a.guid IS NOT NULL AND a.filename IS NOT NULL
        """):
            guid, raw_path = row["guid"], row["filename"]
            if not guid or guid in found or not raw_path:
                continue
            original = Path(raw_path).expanduser()
            candidate = original if original.is_absolute() else root / original
            try:
                path = candidate.resolve(strict=True)
            except (OSError, ValueError):
                continue
            if not any(path.is_relative_to(allowed) for allowed in allowed_roots):
                continue
            if not path.is_file():
                continue
            stat = path.stat()
            if stat.st_size < 1 or stat.st_size > max_bytes:
                continue
            mime = row["mime_type"] or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            found[guid] = {"guid": guid, "path": path, "mime_type": mime,
                           "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        connection.execute("COMMIT")
    finally:
        connection.close()
    return sorted(found.values(), key=lambda item: item["guid"])


def collect_image_candidates(db_path=DEFAULT_MESSAGES_DB,
                             attachments_root=DEFAULT_ATTACHMENTS,
                             max_bytes=MAX_IMAGE_BYTES):
    """Return the image subset for the original image-only sync command."""
    return [item for item in collect_attachment_candidates(db_path, attachments_root, max_bytes)
            if item["mime_type"].startswith("image/") or
            item["path"].suffix.lower() in IMAGE_SUFFIXES]
