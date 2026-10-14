"""Complete, bounded read-only Mail snapshots from the patched Apple PIM CLI."""

import hashlib
import json
import subprocess
from pathlib import Path


MAIL_CLI = Path.home() / ".local/share/personal-context-bridge/bin/mail-cli"
PARTITIONS = 32


def list_mailboxes(command=str(MAIL_CLI)):
    result = subprocess.run([command, "mailboxes", "--engine", "sqlite", "--format", "json"],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("Mail mailbox inventory failed: " + result.stderr[-500:])
    value = json.loads(result.stdout)
    mailboxes = value.get("mailboxes")
    if value.get("success") is not True or value.get("engine") != "sqlite" or not isinstance(mailboxes, list):
        raise ValueError("Mail mailbox inventory is incomplete")
    urls = set()
    for mailbox in mailboxes:
        if (not isinstance(mailbox, dict) or not isinstance(mailbox.get("mailboxUrl"), str)
                or not mailbox["mailboxUrl"] or not isinstance(mailbox.get("localMailboxId"), int)
                or mailbox["localMailboxId"] <= 0 or not isinstance(mailbox.get("messageCount"), int)
                or mailbox["messageCount"] < 0):
            raise ValueError("Mail mailbox inventory has an invalid entry")
        if mailbox["mailboxUrl"] in urls:
            raise ValueError("Mail mailbox inventory has duplicate URLs")
        urls.add(mailbox["mailboxUrl"])
    return mailboxes


def _record(message, mailbox, content_available):
    local_id = message.get("localId")
    if not isinstance(local_id, int) or local_id <= 0 or not isinstance(message.get("messageId"), str) or not message["messageId"]:
        raise ValueError("Mail export message is missing an exact ID")
    title = message.get("subject") or "(no subject)"
    if not isinstance(title, str):
        raise ValueError("Mail export message has an invalid subject")
    date = message.get("dateReceived")
    if date is not None and not isinstance(date, str):
        raise ValueError("Mail export message has an invalid date")
    searchable = [message.get("senderAddress", "")]
    for key in ("to", "cc"):
        values = message.get(key, [])
        if isinstance(values, list):
            searchable.extend(value.get("address", "") for value in values if isinstance(value, dict))
    if content_available:
        if not isinstance(message.get("content"), str):
            raise ValueError("Mail export claims a body without content")
        searchable.append(message["content"])
    record_id = mailbox["mailboxUrl"] + "|" + str(local_id)
    payload = dict(message, contentAvailable=content_available,
                   archiveMailboxUrl=mailbox["mailboxUrl"])
    return {"id": record_id, "title": title, "body": "\n".join(x for x in searchable if isinstance(x, str)),
            "start": date, "end": None, "payload": payload}


def parse_export(lines, mailbox, collected_at, limit=50000):
    iterator = iter(lines)
    try:
        header = json.loads(next(iterator))
    except (StopIteration, json.JSONDecodeError) as exc:
        raise ValueError("Mail export has no valid header") from exc
    if not isinstance(header, dict):
        raise ValueError("Mail export header is invalid")
    count = header.get("count")
    if (header.get("type") != "header" or header.get("mailboxRowid") != mailbox["localMailboxId"]
            or not isinstance(count, int) or count < 0 or count >= limit
            or header.get("totalInMailbox") != count):
        raise ValueError("Mail export header is incomplete or truncated")
    buckets = [[] for _ in range(PARTITIONS)]
    seen = set()
    missing = 0
    footer = None
    for line in iterator:
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("Mail export contains invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Mail export contains invalid JSON object")
        if value.get("type") == "footer":
            footer = value
            break
        if value.get("type") != "message" or not isinstance(value.get("message"), dict) or not isinstance(value.get("contentAvailable"), bool):
            raise ValueError("Mail export contains an invalid message")
        record = _record(value["message"], mailbox, value["contentAvailable"])
        if record["id"] in seen:
            raise ValueError("Mail export contains duplicate local IDs")
        seen.add(record["id"])
        missing += not value["contentAvailable"]
        partition = int.from_bytes(hashlib.sha256(record["id"].encode()).digest()[:4], "big") % PARTITIONS
        buckets[partition].append(record)
    if (footer is None or footer.get("exported") != count or footer.get("missingBodies") != missing
            or len(seen) != count):
        raise ValueError("Mail export ended before a complete snapshot")
    if any(line.strip() for line in iterator):
        raise ValueError("Mail export contains data after its footer")
    return [{"schema": 1, "source": "apple-pim", "kind": "mail",
             "scope": "mail:" + mailbox["mailboxUrl"] + ":bucket:" + str(index),
             "collected_at": collected_at, "complete": True, "records": records}
            for index, records in enumerate(buckets)], missing


def export_mailbox(mailbox, collected_at, command=str(MAIL_CLI), limit=50000):
    args = [command, "export", "--mailbox-rowid", str(mailbox["localMailboxId"]),
            "--limit", str(limit)]
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        batches, missing = parse_export(process.stdout, mailbox, collected_at, limit)
        stderr = process.stderr.read()
        if process.wait(timeout=1800):
            raise RuntimeError("Mail export failed: " + stderr[-500:])
        return batches, missing
    except Exception:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise


def recent_mailbox(mailbox, since, collected_at, command=str(MAIL_CLI), limit=5000):
    """Read exact recent local copies without deleting older mailbox records."""
    args = [command, "messages", "--mailbox-rowid", str(mailbox["localMailboxId"]),
            "--since", since, "--limit", str(limit), "--engine", "sqlite", "--format", "json"]
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError("recent Mail listing failed: " + result.stderr[-300:])
    value = json.loads(result.stdout)
    summaries = value.get("messages")
    if (value.get("success") is not True or value.get("engine") != "sqlite"
            or not isinstance(summaries, list) or len(summaries) >= limit):
        raise ValueError("recent Mail listing is incomplete or reached its limit")
    buckets = [[] for _ in range(PARTITIONS)]
    seen = set()
    missing = 0
    for summary in summaries:
        if not isinstance(summary, dict) or not isinstance(summary.get("localId"), int):
            raise ValueError("recent Mail listing has an invalid local ID")
        local_id = summary["localId"]
        if local_id in seen:
            raise ValueError("recent Mail listing contains duplicate local IDs")
        seen.add(local_id)
        detail = subprocess.run([command, "get", "--local-id", str(local_id),
                                 "--engine", "sqlite", "--format", "json"],
                                capture_output=True, text=True, timeout=120)
        if detail.returncode:
            if "Local .emlx not found" not in detail.stderr:
                raise RuntimeError("recent Mail detail failed: " + detail.stderr[-300:])
            message, available = summary, False
            missing += 1
        else:
            value = json.loads(detail.stdout)
            message = value.get("message")
            if value.get("success") is not True or not isinstance(message, dict) or message.get("localId") != local_id:
                raise ValueError("recent Mail detail is incomplete")
            available = True
        record = _record(message, mailbox, available)
        partition = int.from_bytes(hashlib.sha256(record["id"].encode()).digest()[:4], "big") % PARTITIONS
        buckets[partition].append(record)
    batches = [{"schema": 1, "source": "apple-pim", "kind": "mail",
                "scope": "mail:" + mailbox["mailboxUrl"] + ":bucket:" + str(index),
                "collected_at": collected_at, "complete": False, "records": records}
               for index, records in enumerate(buckets) if records]
    if not batches:
        # Record a successful recent scan even when this mailbox has no new local copies.
        # An incomplete empty batch updates freshness without tombstoning older mail.
        batches.append({"schema": 1, "source": "apple-pim", "kind": "mail",
                        "scope": "mail:" + mailbox["mailboxUrl"] + ":bucket:0",
                        "collected_at": collected_at, "complete": False, "records": []})
    return batches, missing
