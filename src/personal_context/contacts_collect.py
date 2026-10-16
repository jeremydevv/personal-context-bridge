"""Complete read-only Contacts.app snapshots through macOS automation."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .mac_app_lifecycle import collected_app


SCRIPT = Path(__file__).with_name("contacts_snapshot.js")
PARTITIONS = 16
GROUPS = ("emails", "phones", "addresses", "urls", "relatedNames",
          "instantMessages", "socialProfiles")
SEARCH_FIELDS = ("name", "firstName", "middleName", "lastName", "nickname",
                 "organization", "department", "jobTitle", "note", "homePage")


def parse_contacts_snapshot(value, collected_at, limit=50000):
    if (not isinstance(value, dict) or value.get("success") is not True
            or not isinstance(value.get("count"), int) or value["count"] >= limit
            or not isinstance(value.get("contacts"), list)
            or len(value["contacts"]) != value["count"]):
        raise ValueError("Contacts snapshot is incomplete or malformed")
    buckets = [[] for _ in range(PARTITIONS)]
    seen = set()
    for contact in value["contacts"]:
        if not isinstance(contact, dict):
            raise ValueError("Contacts snapshot contains an invalid contact")
        identifier = contact.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("Contacts snapshot contains missing or duplicate IDs")
        seen.add(identifier)
        name = contact.get("name")
        if not isinstance(name, str):
            raise ValueError("Contacts snapshot contains an invalid name")
        for group in GROUPS:
            items = contact.get(group)
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("Contacts snapshot contains incomplete details")
            items.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
        searchable = [contact.get(field) for field in SEARCH_FIELDS]
        for group in GROUPS:
            for item in contact[group]:
                searchable.extend(item.values())
        record = {"id": identifier, "title": name or contact.get("organization") or "(unnamed contact)",
                  "body": "\n".join(part for part in searchable if isinstance(part, str) and part),
                  "start": contact.get("modificationDate") or None, "end": None,
                  "payload": contact}
        bucket = int.from_bytes(hashlib.sha256(identifier.encode()).digest()[:4], "big") % PARTITIONS
        buckets[bucket].append(record)
    return [{"schema": 1, "source": "apple-local", "kind": "contact",
             "scope": "contacts:bucket:" + str(index), "collected_at": collected_at,
             "complete": True, "records": records}
            for index, records in enumerate(buckets)], {"contacts": len(seen)}


def collect_contacts_snapshot(command="/usr/bin/osascript", limit=50000):
    with collected_app("Contacts", command):
        result = subprocess.run([command, "-l", "JavaScript", str(SCRIPT)],
                                capture_output=True, text=True, timeout=900)
        if result.returncode:
            raise RuntimeError("Contacts automation failed: " + result.stderr[-500:])
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Contacts automation returned invalid JSON") from exc
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return parse_contacts_snapshot(value, timestamp, limit)
