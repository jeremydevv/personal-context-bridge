"""Complete read-only Apple Notes snapshots through Notes.app automation."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .mac_app_lifecycle import collected_app


SCRIPT = Path(__file__).with_name("notes_snapshot.js")
PARTITIONS = 16


def parse_notes_snapshot(value, collected_at, limit=50000):
    if (not isinstance(value, dict) or value.get("success") is not True
            or not isinstance(value.get("count"), int) or value["count"] >= limit
            or not isinstance(value.get("notes"), list)
            or len(value["notes"]) != value["count"]
            or not isinstance(value.get("missingBodies"), int)):
        raise ValueError("Notes snapshot is incomplete or malformed")
    buckets = [[] for _ in range(PARTITIONS)]
    seen = set()
    missing = 0
    for note in value["notes"]:
        if not isinstance(note, dict):
            raise ValueError("Notes snapshot contains an invalid note")
        identifier = note.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("Notes snapshot contains missing or duplicate IDs")
        seen.add(identifier)
        if (not isinstance(note.get("title"), str) or not isinstance(note.get("body"), str)
                or not isinstance(note.get("folder"), str)
                or not isinstance(note.get("contentAvailable"), bool)
                or not isinstance(note.get("createdAt"), str)
                or not isinstance(note.get("modifiedAt"), str)):
            raise ValueError("Notes snapshot contains incomplete note details")
        missing += not note["contentAvailable"]
        record = {
            "id": identifier, "title": note["title"],
            "body": note["body"] + "\n" + note["folder"],
            "start": note["modifiedAt"], "end": None,
            "payload": note,
        }
        bucket = int.from_bytes(hashlib.sha256(identifier.encode()).digest()[:4], "big") % PARTITIONS
        buckets[bucket].append(record)
    if missing != value["missingBodies"]:
        raise ValueError("Notes snapshot body availability count is inconsistent")
    return [{"schema": 1, "source": "apple-local", "kind": "note",
             "scope": "notes:bucket:" + str(index), "collected_at": collected_at,
             "complete": True, "records": records}
            for index, records in enumerate(buckets)], {"notes": len(seen), "missing_bodies": missing}


def collect_notes(command="/usr/bin/osascript", limit=50000):
    from .headless_collect import adapter_options
    options = adapter_options("notes")
    if options["mode"] == "database":
        from .notes_database import consistent_snapshot, database_snapshot, legacy_database_snapshot
        database = options.get("database")
        if not isinstance(database, str) or not Path(database).is_absolute():
            raise ValueError("database Notes needs an explicit absolute database path")
        with consistent_snapshot(database) as snapshot:
            value = database_snapshot(snapshot, limit)
        legacy = options.get("legacy_database")
        existing_legacy = Path.home() / "Library/Containers/com.apple.Notes/Data/Library/Notes/NotesV7.storedata"
        if existing_legacy.exists() and not legacy:
            raise ValueError("database Notes requires explicit legacy_database to preserve all account coverage")
        if legacy:
            if not isinstance(legacy, str) or not Path(legacy).is_absolute():
                raise ValueError("legacy Notes database must be an explicit absolute path")
            with consistent_snapshot(legacy) as snapshot:
                old = legacy_database_snapshot(snapshot, limit)
            value["notes"].extend(old["notes"])
            value["count"] += old["count"]
            value["missingBodies"] += old["missingBodies"]
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        batches, counts = parse_notes_snapshot(value, timestamp, limit)
        counts["replica_freshness"] = "unknown"
        counts["legacy_body_format"] = "textutil-with-original-html" if legacy else None
        return batches, counts
    with collected_app("Notes", command):
        result = subprocess.run([command, "-l", "JavaScript", str(SCRIPT)],
                                capture_output=True, text=True, timeout=900)
        if result.returncode:
            raise RuntimeError("Notes automation failed: " + result.stderr[-500:])
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Notes automation returned invalid JSON") from exc
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return parse_notes_snapshot(value, timestamp, limit)
