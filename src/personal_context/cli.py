"""Local collection, SSH transfer, and server-side ingest entrypoints."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .collect import collect_batches, collect_recent_calendar, run_cli
from .contacts_collect import collect_contacts_snapshot
from .mail_collect import list_mailboxes, export_mailbox, recent_mailbox, request_mail_refresh
from .messages_collect import collect_messages
from .image_archive import (collect_image_candidates, collect_attachment_candidates,
                            MAX_IMAGE_BYTES, MAX_ATTACHMENT_BYTES)
from .notes_collect import collect_notes
from .spool import Spool
from .store import Store


SERVER_KEY_PATH = os.environ.get("PERSONAL_CONTEXT_REMOTE_KEY_FILE", "/run/personal-context-bridge/archive.key")


def spool_path_for(root, action, lane):
    """Separate simultaneous full and fast retries without losing full queues."""
    if lane not in ("full", "fast"):
        raise ValueError("invalid sync lane")
    root = Path(root)
    if action == "mail-fast-sync":
        return root / "mail-fast-sync"
    if action in ("mail-sync", "messages-sync", "notes-sync", "contacts-sync", "voice-memos-sync"):
        return root / action if lane == "full" else root / (action + "-fast")
    return root if lane == "full" else root / "fast-sync"


def require_archive_key():
    key_file = os.environ.get("PERSONAL_CONTEXT_KEY_FILE")
    if not key_file or not Path(key_file).is_file():
        raise RuntimeError("encrypted archive key file is required")


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("calendar_ids", "reminder_ids"):
        if not isinstance(config.get(key), list) or any(not isinstance(x, str) or not x for x in config[key]):
            raise ValueError(key + " must be a list of source IDs")
    if not isinstance(config.get("all_calendars", False), bool):
        raise ValueError("all_calendars must be a boolean")
    if not isinstance(config.get("all_reminders", False), bool):
        raise ValueError("all_reminders must be a boolean")
    if not isinstance(config.get("all_contacts", False), bool):
        raise ValueError("all_contacts must be a boolean")
    if not isinstance(config.get("all_mailboxes", False), bool):
        raise ValueError("all_mailboxes must be a boolean")
    if not isinstance(config.get("all_messages", False), bool):
        raise ValueError("all_messages must be a boolean")
    if not isinstance(config.get("all_voice_memos", False), bool):
        raise ValueError("all_voice_memos must be a boolean")
    if not isinstance(config.get("all_notes", False), bool):
        raise ValueError("all_notes must be a boolean")
    if not isinstance(config.get("mailbox_urls", []), list) or any(not isinstance(x, str) or not x for x in config.get("mailbox_urls", [])):
        raise ValueError("mailbox_urls must be a list of source URLs")
    if not config["calendar_ids"] and not config["reminder_ids"] and not config.get("all_calendars") and not config.get("all_reminders") and not config.get("all_contacts") and not config.get("all_mailboxes") and not config.get("mailbox_urls") and not config.get("all_messages") and not config.get("all_notes") and not config.get("all_voice_memos"):
        raise ValueError("select at least one Apple source")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", config.get("remote_host", "")):
        raise ValueError("remote_host must be an SSH alias or host name")
    if not Path(config.get("remote_project", "")).is_absolute():
        raise ValueError("remote_project must be an absolute path")
    return config


def deliver_ssh(config, payload, timeout=180):
    remote_project = Path(config["remote_project"])
    remote_command = shlex.join([
        "env", "PERSONAL_CONTEXT_KEY_FILE=" + SERVER_KEY_PATH,
        str(remote_project / ".venv/bin/python"), "-m", "personal_context.cli",
        "ingest-stdin", "--db", str(Path(config.get("remote_data_dir", str(remote_project / "data"))) / "context.sqlite3"),
    ])
    result = subprocess.run([
        "ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
        "-o", "ConnectionAttempts=1", config["remote_host"], remote_command,
    ], input=payload, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("remote ingest failed: " + result.stderr.decode(errors="replace")[:500])


def remote_image_command(config, action, *extra):
    remote = Path(config["remote_project"])
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "ConnectionAttempts=1", config["remote_host"],
            shlex.join(["env", "PERSONAL_CONTEXT_KEY_FILE=" + SERVER_KEY_PATH,
                         str(remote / ".venv/bin/python"), "-m", "personal_context.cli",
                         action, "--db", str(Path(config.get("remote_data_dir", str(remote / "data"))) / "context.sqlite3"), *extra])]


def sync_message_images(config, limit=100):
    if not config.get("all_messages"):
        raise ValueError("enable all_messages before image sync")
    result = subprocess.run(remote_image_command(config, "image-index"),
                            capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError("remote image index failed: " + result.stderr.decode(errors="replace")[-500:])
    known = {item["guid"]: item for item in json.loads(result.stdout)["images"]}
    candidates = collect_image_candidates()
    pending = [item for item in candidates if
               item["guid"] not in known or
               known[item["guid"]]["bytes"] != item["bytes"] or
               known[item["guid"]]["source_mtime_ns"] != item["mtime_ns"]]
    selected = pending if limit == 0 else pending[:limit]
    imported = 0
    for item in selected:
        command = remote_image_command(
            config, "ingest-image-stdin", "--guid", item["guid"],
            "--mime-type", item["mime_type"], "--bytes", str(item["bytes"]),
            "--mtime-ns", str(item["mtime_ns"]))
        with item["path"].open("rb") as source:
            result = subprocess.run(command, stdin=source, capture_output=True, timeout=1800)
        if result.returncode:
            raise RuntimeError("remote image ingest failed: " + result.stderr.decode(errors="replace")[-500:])
        current = item["path"].stat()
        if current.st_size != item["bytes"] or current.st_mtime_ns != item["mtime_ns"]:
            raise RuntimeError("image changed during transfer; retry on the next sync")
        imported += 1
    return {"available_images": len(candidates), "pending_before_run": len(pending),
            "imported": imported, "remaining": len(pending) - imported}


def sync_message_attachments(config, limit=100):
    """Stream available Messages files over SSH, reusing previously encrypted blobs."""
    if not config.get("all_messages"):
        raise ValueError("enable all_messages before attachment sync")
    result = subprocess.run(remote_image_command(config, "attachment-index"),
                            capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError("remote attachment index failed: " + result.stderr.decode(errors="replace")[-500:])
    known = {item["guid"]: item for item in json.loads(result.stdout)["attachments"]}
    candidates = collect_attachment_candidates()
    pending = [item for item in candidates if
               item["guid"] not in known or
               known[item["guid"]]["bytes"] != item["bytes"] or
               known[item["guid"]]["source_mtime_ns"] != item["mtime_ns"]]
    selected = pending if limit == 0 else pending[:limit]
    imported = 0
    for item in selected:
        command = remote_image_command(
            config, "ingest-attachment-stdin", "--guid", item["guid"],
            "--mime-type", item["mime_type"], "--bytes", str(item["bytes"]),
            "--mtime-ns", str(item["mtime_ns"]))
        with item["path"].open("rb") as source:
            result = subprocess.run(command, stdin=source, capture_output=True, timeout=3600)
        if result.returncode:
            raise RuntimeError("remote attachment ingest failed: " + result.stderr.decode(errors="replace")[-500:])
        current = item["path"].stat()
        if current.st_size != item["bytes"] or current.st_mtime_ns != item["mtime_ns"]:
            raise RuntimeError("attachment changed during transfer; retry on the next sync")
        imported += 1
    return {"available_files": len(candidates), "pending_before_run": len(pending),
            "imported": imported, "remaining": len(pending) - imported}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="personal-context")
    sub = parser.add_subparsers(dest="action", required=True)
    ingest = sub.add_parser("ingest-stdin", help="server: ingest queued batches from standard input")
    ingest.add_argument("--db", required=True)
    image_index = sub.add_parser("image-index", help="server: list archived image IDs and source versions")
    image_index.add_argument("--db", required=True)
    attachment_index = sub.add_parser("attachment-index", help="server: list archived Messages file IDs")
    attachment_index.add_argument("--db", required=True)
    ingest_image = sub.add_parser("ingest-image-stdin", help="server: encrypt one streamed Messages image")
    ingest_image.add_argument("--db", required=True)
    ingest_image.add_argument("--guid", required=True)
    ingest_image.add_argument("--mime-type", required=True)
    ingest_image.add_argument("--bytes", type=int, required=True)
    ingest_image.add_argument("--mtime-ns", type=int, required=True)
    ingest_attachment = sub.add_parser("ingest-attachment-stdin", help="server: encrypt one streamed Messages file")
    ingest_attachment.add_argument("--db", required=True)
    ingest_attachment.add_argument("--guid", required=True)
    ingest_attachment.add_argument("--mime-type", required=True)
    ingest_attachment.add_argument("--bytes", type=int, required=True)
    ingest_attachment.add_argument("--mtime-ns", type=int, required=True)
    for name in ("collect", "flush", "sync", "fast-sync"):
        command = sub.add_parser(name, help="Mac: collect and/or transfer selected Apple data")
        command.add_argument("--config", required=True)
    mail_sync = sub.add_parser("mail-sync", help="Mac: stream selected Mail mailboxes into the encrypted archive")
    mail_sync.add_argument("--config", required=True)
    mail_fast_sync = sub.add_parser("mail-fast-sync", help="Mac: sync recent selected Inbox and Sent copies")
    mail_fast_sync.add_argument("--config", required=True)
    messages_sync = sub.add_parser("messages-sync", help="Mac: stream a complete Messages snapshot into the encrypted archive")
    messages_sync.add_argument("--config", required=True)
    notes_sync = sub.add_parser("notes-sync", help="Mac: stream a complete Notes snapshot into the encrypted archive")
    notes_sync.add_argument("--config", required=True)
    voice_sync = sub.add_parser("voice-memos-sync", help="Mac: sync Voice Memos and full embedded transcripts")
    voice_sync.add_argument("--config", required=True)
    voice_worker = sub.add_parser("voice-worker", help="server: Voice Memo audio and analysis")
    voice_worker.add_argument("--db", required=True)
    voice_worker.add_argument("worker_action", choices=["process", "audio-index", "ingest-audio"])
    voice_worker.add_argument("--record-id")
    voice_worker.add_argument("--sha256")
    voice_worker.add_argument("--bytes", type=int)
    voice_worker.add_argument("--limit", type=int, default=20)
    contacts_sync = sub.add_parser("contacts-sync", help="Mac: stream a complete Contacts snapshot into the encrypted archive")
    contacts_sync.add_argument("--config", required=True)
    image_sync = sub.add_parser("image-sync", help="Mac: stream changed Messages images to encrypted blob storage")
    image_sync.add_argument("--config", required=True)
    image_sync.add_argument("--limit", type=int, default=100)
    attachment_sync = sub.add_parser("attachment-sync", help="Mac: stream changed Messages files to encrypted storage")
    attachment_sync.add_argument("--config", required=True)
    attachment_sync.add_argument("--limit", type=int, default=100)
    discover = sub.add_parser("discover", help="Mac: list available calendar and reminder list IDs")
    status = sub.add_parser("status", help="server: show last successful sync times")
    status.add_argument("--db", required=True)
    health = sub.add_parser("health", help="server: show aggregate source counts and stale scopes")
    health.add_argument("--db", required=True)
    health.add_argument("--fail-on-stale", action="store_true")
    health.add_argument("--fail-on-low-space", action="store_true")
    health.add_argument("--fail-on-inventory-drift", action="store_true")
    backup = sub.add_parser("backup", help="server: make a consistent encrypted archive copy")
    backup.add_argument("--db", required=True)
    backup.add_argument("--output", required=True)
    rebuild = sub.add_parser("rebuild-contact-activity", help="server: atomically backfill the encrypted contact activity index")
    rebuild.add_argument("--db", required=True)
    args = parser.parse_args(argv)

    if args.action == "voice-worker":
        from .voice_memos_worker import main as voice_main
        command = [args.worker_action, "--db", args.db, "--limit", str(args.limit)]
        for key in ("record_id", "sha256", "bytes"):
            value = getattr(args, key)
            if value is not None:
                command.extend(["--" + key.replace("_", "-"), str(value)])
        return voice_main(command)
    if args.action == "image-index":
        require_archive_key()
        store = Store(args.db)
        try:
            print(json.dumps({"images": store.image_attachment_index()}))
        finally:
            store.close()
        return 0
    if args.action == "attachment-index":
        require_archive_key()
        store = Store(args.db)
        try:
            print(json.dumps({"attachments": store.message_attachment_index()}))
        finally:
            store.close()
        return 0
    if args.action == "ingest-image-stdin":
        require_archive_key()
        if args.bytes < 1 or args.bytes > MAX_IMAGE_BYTES:
            raise ValueError("image size is outside the allowed range")
        from .blob_store import BlobStore
        key = Path(os.environ["PERSONAL_CONTEXT_KEY_FILE"]).read_bytes()
        blobs = BlobStore(Path(args.db).parent / "blobs", key)
        metadata = blobs.ingest(sys.stdin.buffer, max_bytes=args.bytes)
        if metadata["bytes"] != args.bytes:
            raise ValueError("transferred image size did not match source metadata")
        store = Store(args.db)
        try:
            store.upsert_image_attachment(args.guid, metadata["object_id"], args.mime_type,
                                          args.bytes, args.mtime_ns, metadata["sha256"])
        finally:
            store.close()
        print(json.dumps({"ok": True, "sha256": metadata["sha256"],
                          "object_id": metadata["object_id"], "bytes": metadata["bytes"]}))
        return 0
    if args.action == "ingest-attachment-stdin":
        require_archive_key()
        if args.bytes < 1 or args.bytes > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment size is outside the allowed range")
        from .blob_store import BlobStore
        key = Path(os.environ["PERSONAL_CONTEXT_KEY_FILE"]).read_bytes()
        blobs = BlobStore(Path(args.db).parent / "blobs", key)
        metadata = blobs.ingest(sys.stdin.buffer, max_bytes=args.bytes)
        if metadata["bytes"] != args.bytes:
            raise ValueError("transferred attachment size did not match source metadata")
        store = Store(args.db)
        try:
            store.upsert_message_attachment(args.guid, metadata["object_id"], args.mime_type,
                                            args.bytes, args.mtime_ns, metadata["sha256"])
        finally:
            store.close()
        print(json.dumps({"ok": True, "sha256": metadata["sha256"],
                          "object_id": metadata["object_id"], "bytes": metadata["bytes"]}))
        return 0

    if args.action == "ingest-stdin":
        require_archive_key()
        payload = json.load(sys.stdin)
        batches = payload.get("batches") if isinstance(payload, dict) and "batches" in payload else [payload]
        if not isinstance(batches, list) or not batches:
            raise ValueError("ingest requires at least one batch")
        for batch in batches:
            if not isinstance(batch, dict):
                raise ValueError("ingest batch must be an object")
            Store._validate(batch)
        store = Store(args.db)
        try:
            for batch in batches:
                store.ingest(batch)
        finally:
            store.close()
        print(json.dumps({"ok": True, "batches": len(batches),
                          "count": sum(len(batch["records"]) for batch in batches)}))
        return 0
    if args.action == "status":
        require_archive_key()
        store = Store(args.db)
        try:
            print(json.dumps({"calendar_last_sync": store.last_sync("calendar"),
                              "reminder_last_sync": store.last_sync("reminder"),
                              "contact_last_sync": store.last_sync("contact"),
                              "mail_last_sync": store.last_sync("mail"),
                              "message_last_sync": store.last_sync("message"),
                              "note_last_sync": store.last_sync("note")}))
        finally:
            store.close()
        return 0
    if args.action == "rebuild-contact-activity":
        require_archive_key()
        store = Store(args.db)
        try:
            store.rebuild_record_identifiers()
            count = store.db.execute("SELECT count(*) FROM record_identifiers").fetchone()[0]
        finally:
            store.close()
        print(json.dumps({"ok": True, "indexed_identifiers": count}))
        return 0
    if args.action == "health":
        require_archive_key()
        store = Store(args.db, read_only=True)
        try:
            report = store.health()
            print(json.dumps(report))
        finally:
            store.close()
        stale = any(source["stale_scopes"] for source in report["sources"].values())
        inventories = (report["sources"][kind].get("inventory") for kind in ("calendar", "reminder", "mail"))
        drift = any(inventory and (inventory["added_last_scan"] or inventory["missing_sources"])
                    for inventory in inventories)
        return 2 if (args.fail_on_stale and stale) or (
            args.fail_on_low_space and report["storage"]["low_space"]) or (
            args.fail_on_inventory_drift and drift) else 0
    if args.action == "backup":
        require_archive_key()
        from sqlcipher3 import dbapi2 as driver
        destination = Path(args.output)
        if not Path(args.db).is_file():
            raise ValueError("archive does not exist")
        if destination.exists() or destination.is_symlink():
            raise ValueError("backup destination must not exist")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination.parent.chmod(0o700)
        key = Path(os.environ["PERSONAL_CONTEXT_KEY_FILE"]).read_bytes()
        source = Store(args.db)
        target = driver.connect(str(destination))
        try:
            target.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
            source.db.backup(target)
            target.close()
            source.close()
            destination.chmod(0o600)
            with destination.open("rb") as stream:
                if stream.read(16) == b"SQLite format 3\x00":
                    raise RuntimeError("backup is unexpectedly plaintext")
            verify = Store(destination)
            verify.close()
        except Exception:
            target.close()
            source.close()
            destination.unlink(missing_ok=True)
            raise
        print(json.dumps({"ok": True, "bytes": destination.stat().st_size}))
        return 0
    if args.action == "discover":
        print(json.dumps({"calendars": run_cli(["calendar-cli", "list"])["calendars"],
                          "reminder_lists": run_cli(["reminder-cli", "lists"])["lists"]}, indent=2))
        return 0

    config = load_config(args.config)
    if args.action == "image-sync":
        if args.limit < 0:
            raise ValueError("image sync limit must be nonnegative")
        print(json.dumps(sync_message_images(config, args.limit)))
        return 0
    if args.action == "attachment-sync":
        if args.limit < 0:
            raise ValueError("attachment sync limit must be nonnegative")
        print(json.dumps(sync_message_attachments(config, args.limit)))
        return 0
    spool_dir = spool_path_for(
        Path(config.get("spool_dir", "~/.local/share/personal-context-bridge/spool")).expanduser(),
        args.action, os.environ.get("PERSONAL_CONTEXT_SYNC_LANE", "full"))
    spool = Spool(spool_dir)
    if args.action == "messages-sync":
        if not config.get("all_messages"):
            raise ValueError("enable all_messages before Messages sync")
        spool.flush(lambda payload: deliver_ssh(config, payload))
        batches, counts = collect_messages()
        for batch in batches:
            spool.enqueue([batch])
            spool.flush(lambda payload: deliver_ssh(config, payload))
        print(json.dumps({**counts, "batches": len(batches)}))
        return 0
    if args.action == "voice-memos-sync":
        if not config.get("all_voice_memos"):
            raise ValueError("enable all_voice_memos before Voice Memos sync")
        from .voice_memos_sync import sync as sync_voice_memos
        print(json.dumps(sync_voice_memos(config, spool)))
        return 0
    if args.action == "notes-sync":
        if not config.get("all_notes"):
            raise ValueError("enable all_notes before Notes sync")
        spool.flush(lambda payload: deliver_ssh(config, payload))
        batches, counts = collect_notes()
        for batch in batches:
            spool.enqueue([batch])
            spool.flush(lambda payload: deliver_ssh(config, payload))
        print(json.dumps({**counts, "batches": len(batches)}))
        return 0
    if args.action == "contacts-sync":
        if not config.get("all_contacts"):
            raise ValueError("enable all_contacts before Contacts sync")
        spool.flush(lambda payload: deliver_ssh(config, payload))
        batches, counts = collect_contacts_snapshot()
        for batch in batches:
            spool.enqueue([batch])
            spool.flush(lambda payload: deliver_ssh(config, payload))
        print(json.dumps({**counts, "batches": len(batches)}))
        return 0
    if args.action in ("mail-sync", "mail-fast-sync"):
        selected = set(config.get("mailbox_urls", []))
        if not selected and not config.get("all_mailboxes"):
            raise ValueError("select mailboxes before Mail sync")
        request_mail_refresh()
        mailboxes = list_mailboxes()
        if selected - {item["mailboxUrl"] for item in mailboxes}:
            raise ValueError("configured Mail mailbox is unavailable")
        spool.flush(lambda payload: deliver_ssh(config, payload, timeout=1800))
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        chosen = mailboxes if config.get("all_mailboxes") else [item for item in mailboxes if item["mailboxUrl"] in selected]
        if args.action == "mail-fast-sync":
            since = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            for index, mailbox in enumerate(chosen, 1):
                batches, missing = recent_mailbox(mailbox, since, timestamp)
                for offset in range(0, len(batches), 4):
                    spool.enqueue(batches[offset:offset + 4])
                    spool.flush(lambda payload: deliver_ssh(config, payload, timeout=1800))
                print(json.dumps({"mailbox_index": index, "mailbox_count": len(chosen),
                                  "recent_records": sum(len(batch["records"]) for batch in batches),
                                  "missing_bodies": missing}), flush=True)
            return 0
        for index, mailbox in enumerate(chosen, 1):
            batches, missing = export_mailbox(mailbox, timestamp, limit=config.get("limit", 50000))
            for offset in range(0, len(batches), 4):
                spool.enqueue(batches[offset:offset + 4])
                spool.flush(lambda payload: deliver_ssh(config, payload, timeout=1800))
            print(json.dumps({"mailbox_index": index, "mailbox_count": len(chosen),
                              "records": sum(len(batch["records"]) for batch in batches),
                              "missing_bodies": missing}), flush=True)
        if config.get("all_mailboxes"):
            spool.enqueue([{"schema": 1, "source": "apple-pim", "kind": "inventory",
                            "scope": "mail", "collected_at": timestamp, "complete": True,
                            "records": [{"id": mailbox["mailboxUrl"], "title": mailbox["mailboxUrl"]}
                                        for mailbox in mailboxes]}])
            spool.flush(lambda payload: deliver_ssh(config, payload, timeout=1800))
        return 0
    if args.action in ("collect", "sync", "fast-sync"):
        calendar_ids = config["calendar_ids"]
        reminder_ids = config["reminder_ids"]
        if config.get("all_calendars"):
            listing = run_cli(["calendar-cli", "list"])
            visible = listing.get("calendars")
            if not isinstance(visible, list):
                raise RuntimeError("calendar inventory is incomplete")
            calendar_ids = [item.get("id") if isinstance(item, dict) else None for item in visible]
            if (not calendar_ids or any(not isinstance(identifier, str) or not identifier for identifier in calendar_ids)
                    or len(calendar_ids) != len(set(calendar_ids))):
                raise RuntimeError("calendar inventory has missing or duplicate IDs")
        if config.get("all_reminders"):
            listing = run_cli(["reminder-cli", "lists"])
            visible = listing.get("lists")
            if not isinstance(visible, list):
                raise RuntimeError("reminder inventory is incomplete")
            reminder_ids = [item.get("id") if isinstance(item, dict) else None for item in visible]
            if (not reminder_ids or any(not isinstance(identifier, str) or not identifier for identifier in reminder_ids)
                    or len(reminder_ids) != len(set(reminder_ids))):
                raise RuntimeError("reminder inventory has missing or duplicate IDs")
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        batches = []
        if args.action == "fast-sync":
            today = datetime.now(timezone.utc).date()
            archive_from = config.get("from_date", "1970-01-01")
            archive_to = config.get("to_date", "2100-12-31")
            if calendar_ids:
                first = max((today - timedelta(days=366)).isoformat(), archive_from)
                last = min((today + timedelta(days=730)).isoformat(), archive_to)
                if first <= last:
                    batches.extend(collect_recent_calendar(run_cli, calendar_ids, first, last,
                                                           archive_from, archive_to, timestamp,
                                                           config.get("limit", 50000)))
            if reminder_ids:
                batches.extend(collect_batches(run_cli, [], reminder_ids, archive_from, archive_to,
                                               timestamp, config.get("limit", 50000)))
        elif calendar_ids or reminder_ids:
            batches = collect_batches(run_cli, calendar_ids, reminder_ids,
                                      config.get("from_date", "1970-01-01"),
                                      config.get("to_date", "2100-12-31"),
                                      timestamp, config.get("limit", 50000))
        if config.get("all_calendars"):
            batches.append({"schema": 1, "source": "apple-pim", "kind": "inventory",
                            "scope": "calendar", "collected_at": timestamp,
                            "complete": True,
                            "records": [{"id": identifier, "title": identifier}
                                        for identifier in calendar_ids]})
        if config.get("all_reminders"):
            batches.append({"schema": 1, "source": "apple-pim", "kind": "inventory",
                            "scope": "reminder", "collected_at": timestamp,
                            "complete": True,
                            "records": [{"id": identifier, "title": identifier}
                                        for identifier in reminder_ids]})
        spool.enqueue(batches)
        print(json.dumps({"queued_batches": len(batches)}))
    if args.action in ("flush", "sync", "fast-sync"):
        sent = spool.flush(lambda payload: deliver_ssh(config, payload))
        print(json.dumps({"sent_batches": sent, "remaining": len(spool.pending())}))
    return 0


def entrypoint():
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    entrypoint()
