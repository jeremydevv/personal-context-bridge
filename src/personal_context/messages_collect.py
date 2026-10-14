"""Read-only, complete snapshots of the local Apple Messages database."""

import hashlib
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_DB = Path.home() / "Library/Messages/chat.db"
PARTITIONS = 64
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _decoded_body(plain, attributed):
    if plain:
        return plain, True
    if not attributed:
        return "", False
    from typedstream import unarchive_from_data

    try:
        archive = unarchive_from_data(attributed)
        if getattr(getattr(archive, "clazz", None), "name", None) not in (
                b"NSAttributedString", b"NSMutableAttributedString"):
            return "", False
        value = archive.contents[0].value.value
        return (value, True) if isinstance(value, str) else ("", False)
    except (AttributeError, IndexError, TypeError, ValueError):
        return "", False


def _timestamp(value):
    if not isinstance(value, int) or value <= 0:
        return None
    seconds, nanos = divmod(value, 1_000_000_000)
    return (APPLE_EPOCH + timedelta(seconds=seconds, microseconds=nanos // 1000)).isoformat().replace("+00:00", "Z")


def collect_messages(db_path=DEFAULT_DB, collected_at=None, limit=200000):
    """Return partitioned complete batches and counts from one SQLite snapshot."""
    db_path = Path(db_path)
    if not db_path.is_file() or db_path.is_symlink():
        raise ValueError("Messages database is unavailable")
    if collected_at is None:
        collected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    connection = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        count = connection.execute("SELECT COUNT(*) FROM message").fetchone()[0]
        if count >= limit:
            raise ValueError("Messages snapshot reached its configured limit")
        handles = {row["ROWID"]: row["id"] for row in connection.execute("SELECT ROWID,id FROM handle")}
        chat_members = defaultdict(list)
        for row in connection.execute("SELECT chj.chat_id,chj.handle_id FROM chat_handle_join chj"):
            chat_members[row["chat_id"]].append(handles.get(row["handle_id"], ""))
        chats = defaultdict(list)
        for row in connection.execute("""
            SELECT cmj.message_id,c.ROWID AS chat_rowid,c.guid,c.display_name,c.chat_identifier
            FROM chat_message_join cmj JOIN chat c ON c.ROWID=cmj.chat_id
        """):
            chats[row["message_id"]].append({
                "guid": row["guid"], "name": row["display_name"] or "",
                "identifier": row["chat_identifier"] or "",
                "participants": sorted(set(x for x in chat_members[row["chat_rowid"]] if x)),
            })
        attachments = defaultdict(list)
        for row in connection.execute("""
            SELECT maj.message_id,a.guid,a.transfer_name,a.mime_type,a.total_bytes
            FROM message_attachment_join maj JOIN attachment a ON a.ROWID=maj.attachment_id
        """):
            attachments[row["message_id"]].append({
                "guid": row["guid"], "name": row["transfer_name"] or "",
                "mime_type": row["mime_type"] or "", "bytes": row["total_bytes"],
            })
        buckets = [[] for _ in range(PARTITIONS)]
        seen = set()
        missing_bodies = 0
        cursor = connection.execute("""
            SELECT ROWID,guid,text,attributedBody,subject,date,handle_id,is_from_me,
                   service,is_sent,is_read,is_system_message,is_spam,date_edited,
                   date_retracted,associated_message_guid,associated_message_type,
                   reply_to_guid
            FROM message ORDER BY ROWID
        """)
        for row in cursor:
            guid = row["guid"]
            if not isinstance(guid, str) or not guid or guid in seen:
                raise ValueError("Messages snapshot has a missing or duplicate GUID")
            seen.add(guid)
            body, available = _decoded_body(row["text"], row["attributedBody"])
            missing_bodies += not available
            sender = "me" if row["is_from_me"] else handles.get(row["handle_id"], "")
            message_chats = sorted(chats[row["ROWID"]], key=lambda x: x["guid"] or "")
            message_attachments = sorted(attachments[row["ROWID"]], key=lambda x: x["guid"] or "")
            title = row["subject"] or ("Message from " + sender if sender else "Message")
            searchable = [body, sender]
            for chat in message_chats:
                searchable.extend([chat["name"], chat["identifier"], *chat["participants"]])
            searchable.extend(a["name"] for a in message_attachments)
            record = {
                "id": guid, "title": title, "body": "\n".join(x for x in searchable if x),
                "start": _timestamp(row["date"]), "end": None,
                "payload": {
                    "guid": guid, "text": body, "contentAvailable": available,
                    "sender": sender, "fromMe": bool(row["is_from_me"]),
                    "service": row["service"], "sent": bool(row["is_sent"]),
                    "read": bool(row["is_read"]), "system": bool(row["is_system_message"]),
                    "spam": bool(row["is_spam"]), "editedAt": _timestamp(row["date_edited"]),
                    "retractedAt": _timestamp(row["date_retracted"]),
                    "associatedMessageGuid": row["associated_message_guid"],
                    "associatedMessageType": row["associated_message_type"],
                    "replyToGuid": row["reply_to_guid"], "chats": message_chats,
                    "attachments": message_attachments,
                },
            }
            bucket = int.from_bytes(hashlib.sha256(guid.encode()).digest()[:4], "big") % PARTITIONS
            buckets[bucket].append(record)
        if len(seen) != count:
            raise ValueError("Messages snapshot is incomplete")
        connection.execute("COMMIT")
    finally:
        connection.close()
    batches = [{"schema": 1, "source": "apple-local", "kind": "message",
                "scope": "messages:bucket:" + str(index), "collected_at": collected_at,
                "complete": True, "records": records}
               for index, records in enumerate(buckets)]
    return batches, {"messages": count, "missing_bodies": missing_bodies,
                     "attachments": sum(len(x) for x in attachments.values())}
