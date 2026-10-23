"""Stream a Google Maps on-phone Timeline export into the encrypted travel archive.

The input is read from stdin so an export can be piped over SSH without a
plaintext copy on archive-server. Only the phone JSON format with semanticSegments
is accepted; other Takeout formats need a separate parser.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import sys
import time
import uuid

from .location_receiver import SCHEMA

MAX_SOURCE_BYTES = 2 * 1024 ** 3
MAX_SEGMENT_BYTES = 2 * 1024 ** 2
MAX_SEGMENTS = 2_000_000
SOURCE = "google_maps_phone_timeline"
LAT_LNG = re.compile(r"\s*([+-]?\d+(?:\.\d+)?)°?\s*,\s*([+-]?\d+(?:\.\d+)?)°?\s*")


class HashingLimitedReader:
    def __init__(self, reader, limit: int = MAX_SOURCE_BYTES):
        self.reader = reader
        self.limit = limit
        self.count = 0
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        remaining = self.limit - self.count
        size = remaining + 1 if size < 0 else min(size, remaining + 1)
        chunk = self.reader.read(size)
        self.count += len(chunk)
        if self.count > self.limit:
            raise ValueError("Timeline export exceeds the size limit")
        self.digest.update(chunk)
        return chunk


class PrefixedReader:
    def __init__(self, prefix: bytes, reader):
        self.prefix = prefix
        self.reader = reader

    def read(self, size: int = -1) -> bytes:
        if self.prefix:
            if size < 0:
                chunk, self.prefix = self.prefix, b""
                return chunk + self.reader.read()
            chunk, self.prefix = self.prefix[:size], self.prefix[size:]
            return chunk
        return self.reader.read(size)


def parse_timestamp(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError("segment timestamp must be a string")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid segment timestamp") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("segment timestamp needs a timezone")
    return int(instant.astimezone(timezone.utc).timestamp())


def parse_lat_lng(value: object) -> tuple[float | None, float | None]:
    if value is None:
        return None, None
    if isinstance(value, str):
        match = LAT_LNG.fullmatch(value)
        if match is None:
            raise ValueError("invalid latLng string")
        lat, lon = float(match[1]), float(match[2])
    elif isinstance(value, dict):
        lat = value.get("latitude", value.get("lat"))
        lon = value.get("longitude", value.get("lng", value.get("lon")))
        if isinstance(lat, bool) or isinstance(lon, bool) or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            raise ValueError("invalid latLng object")
        lat, lon = float(lat), float(lon)
    else:
        raise ValueError("invalid latLng value")
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("coordinates out of range")
    return lat, lon


def parse_segment(item: object) -> tuple[str, int, int, float | None, float | None, str | None, str]:
    if not isinstance(item, dict):
        raise ValueError("semantic segment must be an object")
    payload = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(payload.encode("utf-8")) > MAX_SEGMENT_BYTES:
        raise ValueError("semantic segment exceeds the size limit")
    start, end = parse_timestamp(item.get("startTime")), parse_timestamp(item.get("endTime"))
    if end < start or end - start > 366 * 86400:
        raise ValueError("invalid semantic segment time range")
    kind = ("visit" if isinstance(item.get("visit"), dict) else
            "activity" if isinstance(item.get("activity"), dict) else
            "path" if isinstance(item.get("timelinePath"), list) else "other")
    candidate = item.get("visit", {}).get("topCandidate", {}) if kind == "visit" else {}
    if not isinstance(candidate, dict):
        candidate = {}
    place_id = candidate.get("placeId")
    if place_id is not None and (not isinstance(place_id, str) or len(place_id) > 512):
        raise ValueError("invalid place ID")
    place_location = candidate.get("placeLocation")
    if not isinstance(place_location, dict):
        place_location = item.get("visit", {}).get("placeLocation", {}) if kind == "visit" else {}
    anchor = place_location.get("latLng") if isinstance(place_location, dict) else None
    if kind == "activity":
        start_location = item["activity"].get("start")
        anchor = start_location.get("latLng") if isinstance(start_location, dict) else None
    elif kind == "path" and item["timelinePath"]:
        first_point = item["timelinePath"][0]
        anchor = first_point.get("point") if isinstance(first_point, dict) else None
    lat, lon = parse_lat_lng(anchor)
    return kind, start, end, lat, lon, place_id, payload


def import_stream(db, reader) -> dict:
    try:
        import ijson
    except ImportError as exc:
        raise RuntimeError("ijson is required for streaming Timeline imports") from exc
    db.executescript(SCHEMA)
    prefix = reader.read(4096)
    first = prefix.lstrip()[:1]
    if first not in (b"{", b"["):
        raise ValueError("Timeline export must be a JSON object or array")
    item_path = "semanticSegments.item" if first == b"{" else "item"
    source = HashingLimitedReader(PrefixedReader(prefix, reader))
    run_id = uuid.uuid4().hex
    seen = inserted = 0
    with db:
        for item in ijson.items(source, item_path, use_float=True):
            seen += 1
            if seen > MAX_SEGMENTS:
                raise ValueError("Timeline export has too many segments")
            kind, start, end, lat, lon, place_id, payload = parse_segment(item)
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            inserted += db.execute(
                "INSERT OR IGNORE INTO timeline_segments "
                "(digest,kind,start_ts,end_ts,lat,lon,place_id,source,first_import_run,payload) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (digest, kind, start, end, lat, lon, place_id, SOURCE, run_id, payload),
            ).rowcount
        if seen == 0:
            raise ValueError("no semanticSegments found; this may be a different Timeline export format")
        db.execute(
            "INSERT INTO timeline_imports VALUES (?,?,?,?,?,?)",
            (run_id, SOURCE, source.digest.hexdigest(), int(time.time()), seen, inserted),
        )
    return {"source": SOURCE, "seen": seen, "inserted": inserted,
            "source_sha256": source.digest.hexdigest(), "run_id": run_id}


def main() -> None:
    from sqlcipher3 import dbapi2 as cipher

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="existing encrypted Travel archive")
    parser.add_argument("--key-file", required=True, help="runtime archive key file")
    args = parser.parse_args()
    key = open(args.key_file, "rb").read()
    if len(key) != 32 or not os.path.isfile(args.db):
        sys.exit("existing encrypted archive and 32-byte runtime key are required")
    db = cipher.connect(args.db)
    try:
        db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
        if not db.execute("PRAGMA cipher_version").fetchone():
            sys.exit("SQLCipher unavailable")
        db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        print(json.dumps(import_stream(db, sys.stdin.buffer)))
    finally:
        db.close()


if __name__ == "__main__":
    main()
