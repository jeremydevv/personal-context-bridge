"""Read selected Apple PIM CLI sources into complete sync batches."""

import json
import copy
import subprocess
from datetime import date


def run_cli(args):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("Apple PIM command failed: " + args[0] + " " + args[1] + ": " + result.stderr.strip()[:500])
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Apple PIM returned invalid JSON") from exc
    if not isinstance(value, dict) or value.get("success") is not True:
        raise RuntimeError("Apple PIM reported an unsuccessful read")
    return value


def _known_ids(run, command, key):
    value = run(command)
    if value.get("success") is not True or not isinstance(value.get(key), list):
        raise ValueError("Apple PIM source listing failed")
    return {item["id"] for item in value[key] if isinstance(item, dict) and isinstance(item.get("id"), str)}


def _record(kind, item):
    if not isinstance(item, dict) or not item.get("id") or not isinstance(item.get("title"), str):
        raise ValueError("Apple PIM returned a record without an ID or title")
    if kind == "calendar":
        item = copy.deepcopy(item)
        # EventKit does not promise stable ordering for these sets. Sorting
        # avoids false history versions every time a calendar is rescanned.
        for field in ("alarms", "attendees"):
            if isinstance(item.get(field), list):
                item[field].sort(key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False))
        start = item.get("startDate")
        if not isinstance(start, str):
            raise ValueError("Calendar event missing start date")
        # Recurring instances can share one EventKit identifier. Include the
        # occurrence start so a complete scan never collapses separate dates.
        record_id = item["id"] + "|" + start
        end = item.get("endDate")
    else:
        record_id = item["id"]
        start = item.get("dueDate")
        end = None
    return {
        "id": record_id,
        "title": item["title"],
        "body": item.get("notes", ""),
        "start": start,
        "end": end,
        "payload": item,
    }


def collect_batches(run, calendar_ids, reminder_ids, date_from, date_to, collected_at, limit=50000):
    if not calendar_ids and not reminder_ids:
        raise ValueError("at least one explicit calendar or reminder list ID is required")
    if limit < 2:
        raise ValueError("limit must be at least 2")
    first_day = date.fromisoformat(date_from)
    last_day = date.fromisoformat(date_to)
    if first_day > last_day:
        raise ValueError("collection date range is inverted")
    windows = []
    year = first_day.year
    while year <= last_day.year:
        end_year = min(year + 2, last_day.year)
        window_start = first_day if year == first_day.year else date(year, 1, 1)
        window_end = last_day if end_year == last_day.year else date(end_year, 12, 31)
        windows.append((year, end_year, window_start.isoformat(), window_end.isoformat()))
        year = end_year + 1
    batches = []
    for kind, ids, listing, listing_key, records_key, source_key in (
        ("calendar", calendar_ids, ["calendar-cli", "list"], "calendars", "events", "calendarId"),
        ("reminder", reminder_ids, ["reminder-cli", "lists"], "lists", "reminders", "listId"),
    ):
        if not ids:
            continue
        known = _known_ids(run, listing, listing_key)
        for source_id in ids:
            if source_id not in known:
                raise ValueError("configured Apple PIM source is unavailable: " + source_id)
            if kind == "calendar":
                buckets = {start_year: {} for start_year, _, _, _ in windows}
                for start_year, end_year, from_day, to_day in windows:
                    args = ["calendar-cli", "events", "--calendar", source_id, "--from", from_day,
                            "--to", to_day, "--limit", str(limit)]
                    value = run(args)
                    items = value.get(records_key)
                    if value.get("success") is not True or not isinstance(items, list):
                        raise ValueError("Apple PIM did not return a complete calendar list")
                    if len(items) >= limit:
                        raise ValueError("Apple PIM read reached its limit; refusing an incomplete scan")
                    if any(not isinstance(item, dict) or item.get(source_key) != source_id for item in items):
                        raise ValueError("Apple PIM returned a record outside the selected source")
                    for item in items:
                        record = _record(kind, item)
                        local_year = int(item.get("localStart", item["startDate"])[:4])
                        for bucket_start, bucket_end, _, _ in windows:
                            if bucket_start <= local_year <= bucket_end:
                                buckets[bucket_start][record["id"]] = record
                                break
                for start_year, end_year, _, _ in windows:
                    batches.append({
                        "schema": 1, "source": "apple-pim", "kind": kind,
                        "scope": "calendar:" + source_id + ":" + str(start_year) + "-" + str(end_year),
                        "collected_at": collected_at, "complete": True,
                        "records": list(buckets[start_year].values()),
                    })
            else:
                args = ["reminder-cli", "items", "--list", source_id, "--filter", "all", "--limit", str(limit)]
                value = run(args)
                items = value.get(records_key)
                if value.get("success") is not True or not isinstance(items, list):
                    raise ValueError("Apple PIM did not return a complete reminder list")
                if len(items) >= limit:
                    raise ValueError("Apple PIM read reached its limit; refusing an incomplete scan")
                if any(not isinstance(item, dict) or item.get(source_key) != source_id for item in items):
                    raise ValueError("Apple PIM returned a record outside the selected source")
                records = [_record(kind, item) for item in items]
                if len({item["id"] for item in records}) != len(records):
                    raise ValueError("duplicate Apple PIM record IDs in a scan")
                batches.append({
                    "schema": 1, "source": "apple-pim", "kind": kind,
                    "scope": "reminder:" + source_id, "collected_at": collected_at,
                    "complete": True, "records": records,
                })
    return batches


def collect_recent_calendar(run, calendar_ids, date_from, date_to, archive_from,
                            archive_to, collected_at, limit=50000):
    """Update recent events in the same three-year scopes as the full archive scan.

    Partial batches preserve events outside this range. The daily complete scan
    remains responsible for removals and changes to older events.
    """
    first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    archive_first, archive_last = date.fromisoformat(archive_from), date.fromisoformat(archive_to)
    if first > last or first < archive_first or last > archive_last or limit < 2:
        raise ValueError("invalid recent calendar range")
    known = _known_ids(run, ["calendar-cli", "list"], "calendars")
    batches = []
    for source_id in calendar_ids:
        if source_id not in known:
            raise ValueError("configured Apple PIM source is unavailable: " + source_id)
        year = archive_first.year
        while year <= archive_last.year:
            end_year = min(year + 2, archive_last.year)
            window_first = max(first, archive_first if year == archive_first.year else date(year, 1, 1))
            window_last = min(last, archive_last if end_year == archive_last.year else date(end_year, 12, 31))
            if window_first <= window_last:
                value = run(["calendar-cli", "events", "--calendar", source_id,
                             "--from", window_first.isoformat(), "--to", window_last.isoformat(),
                             "--limit", str(limit)])
                items = value.get("events")
                if value.get("success") is not True or not isinstance(items, list):
                    raise ValueError("Apple PIM did not return a recent calendar list")
                if len(items) >= limit:
                    raise ValueError("recent calendar read reached its limit")
                if any(not isinstance(item, dict) or item.get("calendarId") != source_id for item in items):
                    raise ValueError("Apple PIM returned an event outside the selected calendar")
                records = {}
                for item in items:
                    record = _record("calendar", item)
                    if year <= int(item.get("localStart", item["startDate"])[:4]) <= end_year:
                        records[record["id"]] = record
                batches.append({"schema": 1, "source": "apple-pim", "kind": "calendar",
                                "scope": "calendar:" + source_id + ":" + str(year) + "-" + str(end_year),
                                "collected_at": collected_at, "complete": False,
                                "records": list(records.values())})
            year = end_year + 1
    return batches


def collect_contacts(run, collected_at, limit=50000):
    """Collect a complete Contacts snapshot only when explicitly enabled."""
    if limit < 2:
        raise ValueError("contact limit must be at least 2")
    listing = run(["contacts-cli", "list", "--limit", str(limit)])
    brief = listing.get("contacts")
    if listing.get("success") is not True or not isinstance(brief, list):
        raise ValueError("Apple PIM did not return a complete contact list")
    if len(brief) >= limit:
        raise ValueError("Apple PIM contact read reached its limit; refusing an incomplete scan")
    ids = [item.get("id") for item in brief if isinstance(item, dict)]
    if len(ids) != len(brief) or any(not isinstance(value, str) or not value for value in ids):
        raise ValueError("Apple PIM returned a contact without an ID")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate Apple PIM contact IDs in a scan")
    records = []
    for contact_id in ids:
        detail = run(["contacts-cli", "get", "--id", contact_id])
        item = detail.get("contact")
        if detail.get("success") is not True or not isinstance(item, dict) or item.get("id") != contact_id:
            raise ValueError("Apple PIM returned incomplete contact detail")
        item = copy.deepcopy(item)
        for field in ("emails", "phones", "addresses", "urls", "instantMessages", "relations", "socialProfiles"):
            if isinstance(item.get(field), list):
                item[field].sort(key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False))
        title = item.get("fullName") or item.get("organization") or "(unnamed contact)"
        if not isinstance(title, str):
            raise ValueError("Apple PIM returned invalid contact name")
        searchable = []
        for field in ("organization", "notes"):
            if isinstance(item.get(field), str):
                searchable.append(item[field])
        for field in ("emails", "phones"):
            values = item.get(field, [])
            if isinstance(values, list):
                searchable.extend(value["value"] for value in values
                                  if isinstance(value, dict) and isinstance(value.get("value"), str))
        records.append({"id": contact_id, "title": title, "body": "\n".join(searchable),
                        "start": None, "end": None, "payload": item})
    return {"schema": 1, "source": "apple-pim", "kind": "contact", "scope": "contacts:all",
            "collected_at": collected_at, "complete": True, "records": records}
