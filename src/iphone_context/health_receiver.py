#!/usr/bin/env python3
"""Private Puls Sync Protocol v1 receiver: HTTP in, SQLCipher out.

Adapted from PulsHealth's Apache-2.0 minimal Python receiver. See
../../third_party/pulshealth/LICENSE and https://github.com/PulsHealth/pulshealth.

Implements the receiver side of docs/protocol/README.md:

    POST /v1/batches       gzip NDJSON batch -> idempotent SQLite writes -> JSON counts
    GET  /v1/capabilities  {"protocolVersions":[1],"features":["batches","profile"],...}
    GET  /healthz          {"ok":true}

Environment: PULS_TOKEN_FILE, PULS_KEY_FILE, PULS_DB (required),
PULS_PORT (default 8787). Listener is always loopback-only. Python 3.11+.
"""
from __future__ import annotations

import gzip
import copy
import hmac
import io
import json
import os
import re
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROTOCOL_VERSIONS = [1]
DEFAULT_USER = "5ea4d000-0000-4000-8000-000000000001"
MAX_BODY = 32 << 20  # compressed bytes
MAX_UNCOMPRESSED = 128 << 20
COUNTS = ("sampleCount", "deletionCount", "routeCount", "seriesCount",
          "aggregateCount", "activitySummaryCount", "profileCount")
# kind -> the detail field that must be present for that kind
KINDS = {"quantity": None, "category": "category", "workout": "workout", "heartbeatSeries": "heartbeats",
         "ecg": "ecg", "stateOfMind": "stateOfMind", "medicationDose": "medicationDose"}
AGG_ENUMS = {"func": {"sum", "average", "min", "max", "mostRecent", "duration"},
             "intervalUnit": {"minute", "hour", "day", "week", "month"},
             "deviceFilter": {"all", "watch", "iphone"}}
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
ZERO_RESULT = {"accepted": 0, "deleted": 0, "duplicates": 0, "routePoints": 0,
               "seriesPoints": 0, "aggregateSamples": 0, "activitySummaries": 0}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT, email TEXT, date_of_birth_ms REAL,
    biological_sex TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS batches (batch_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, device_id TEXT, type TEXT,
    reason TEXT, schema_version INTEGER, client_version TEXT, exported_at_ms REAL, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS samples (uuid TEXT PRIMARY KEY, user_id TEXT NOT NULL, type TEXT NOT NULL,
    kind TEXT NOT NULL, start_ms REAL NOT NULL, end_ms REAL NOT NULL, value REAL, unit TEXT, category INTEGER,
    source_name TEXT, device TEXT, line TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS samples_by_type ON samples (user_id, type, start_ms);
CREATE INDEX IF NOT EXISTS samples_by_kind_start ON samples (kind, start_ms);
CREATE TABLE IF NOT EXISTS deletions (uuid TEXT PRIMARY KEY, user_id TEXT NOT NULL, type TEXT NOT NULL,
    deleted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS route_points (workout_uuid TEXT NOT NULL, t_ms REAL NOT NULL, user_id TEXT NOT NULL,
    lat REAL NOT NULL, lon REAL NOT NULL, alt REAL, h_acc REAL, v_acc REAL, speed REAL, course REAL,
    PRIMARY KEY (workout_uuid, t_ms));
CREATE TABLE IF NOT EXISTS series_points (workout_uuid TEXT NOT NULL, type TEXT NOT NULL, t_ms REAL NOT NULL,
    user_id TEXT NOT NULL, value REAL NOT NULL, unit TEXT, PRIMARY KEY (workout_uuid, type, t_ms));
CREATE TABLE IF NOT EXISTS aggregates (user_id TEXT NOT NULL, type TEXT NOT NULL, func TEXT NOT NULL,
    interval_value INTEGER NOT NULL, interval_unit TEXT NOT NULL, device_filter TEXT NOT NULL,
    bucket_start_ms REAL NOT NULL, bucket_end_ms REAL NOT NULL, value REAL, unit TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, type, func, interval_value, interval_unit, device_filter, bucket_start_ms));
CREATE TABLE IF NOT EXISTS activity_summaries (user_id TEXT NOT NULL, date TEXT NOT NULL, move_kcal REAL,
    move_goal_kcal REAL, exercise_min REAL, exercise_goal_min REAL, stand_hours REAL, stand_goal_hours REAL,
    move_mode INTEGER, move_time_min REAL, move_time_goal_min REAL, updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, date));
"""


class BadRequest(Exception):
    """Malformed input: answered with 400, which the app never retries."""


class UnsupportedVersion(Exception):
    """A protocol version this receiver does not speak: fixed 400 body."""


def is_uuid(v):
    return isinstance(v, str) and UUID_RE.match(v) is not None


def is_ms(v):
    """A required epoch-ms timestamp: a number in year 1..9999, not 0 (0 means absent)."""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v != 0 and -62135596800000 <= v <= 253402300799999)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_batch(text):
    """NDJSON text -> dict of validated lines in wire order. Raises BadRequest/UnsupportedVersion."""
    lines = iter(line for line in text.split("\n") if line.strip())

    def take(n, what, key=None):
        for i in range(1, n + 1):
            try:
                obj = json.loads(next(lines))
            except StopIteration:
                raise BadRequest(f"{what} {i}/{n}: unexpected end of body") from None
            except ValueError as e:
                raise BadRequest(f"{what} {i}: invalid JSON: {e}") from None
            if key:  # wrapped line: the wrapper key must hold a non-null object
                obj = obj.get(key) if isinstance(obj, dict) else None
            if not isinstance(obj, dict):
                raise BadRequest(f"{what} {i}: missing or null {key or 'object'}")
            yield i, obj

    def points(inner, what, i, *required):
        pts = inner.get("points")
        if not isinstance(pts, list) or len(pts) > 4000:
            raise BadRequest(f"{what} {i}: points must be a list of at most 4000")
        for p in pts:
            if not isinstance(p, dict) or not is_ms(p.get("t")) or any(p.get(k) is None for k in required):
                raise BadRequest(f"{what} {i}: bad point")
        return pts

    header = next(take(1, "batch header"), (0, None))[1]
    if header is None:
        raise BadRequest("empty body: missing batch header")
    version = header.get("schemaVersion")  # absent or null = legacy client = 1
    if version is not None and version not in PROTOCOL_VERSIONS:
        raise UnsupportedVersion(f"schemaVersion {version}")
    if not is_uuid(header.get("batchID")) or not header.get("type"):
        raise BadRequest("invalid batch header: batchID must be a UUID and type non-empty")
    counts = {k: header.get(k) or 0 for k in COUNTS}
    if any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 100_000 for n in counts.values()):
        raise BadRequest("invalid batch header: counts must be integers 0..100000")
    if counts["profileCount"] > 1 or sum(counts.values()) > 200_000:
        raise BadRequest("invalid batch header: too many declared lines")

    b = {"header": header, "samples": [], "deletions": [], "routes": [], "series": [],
         "aggregates": [], "activitySummaries": [], "profile": None}
    for i, s in take(counts["sampleCount"], "sample"):
        if not is_uuid(s.get("uuid")) or not s.get("type") or s.get("kind") not in KINDS or not is_ms(s.get("start")):
            raise BadRequest(f"sample {i}: bad uuid, type, kind, or start")
        if KINDS[s["kind"]] and s.get(KINDS[s["kind"]]) is None:
            raise BadRequest(f"sample {i}: {s['kind']} sample missing {KINDS[s['kind']]}")
        b["samples"].append(s)
    for i, d in take(counts["deletionCount"], "deletion", "deleted"):
        if not is_uuid(d.get("uuid")) or not d.get("type"):
            raise BadRequest(f"deletion {i}: bad uuid or type")
        b["deletions"].append(d)
    for i, r in take(counts["routeCount"], "route", "route"):
        if not is_uuid(r.get("workoutUUID")):
            raise BadRequest(f"route {i}: workoutUUID is not a UUID")
        points(r, "route", i, "lat", "lon")
        b["routes"].append(r)
    for i, s in take(counts["seriesCount"], "series", "series"):
        if not is_uuid(s.get("workoutUUID")) or not s.get("type"):
            raise BadRequest(f"series {i}: bad workoutUUID or type")
        points(s, "series", i, "value")
        b["series"].append(s)
    for i, a in take(counts["aggregateCount"], "aggregate", "aggregate"):
        iv = a.get("intervalValue")
        if (not a.get("type") or any(a.get(k) not in v for k, v in AGG_ENUMS.items())
                or isinstance(iv, bool) or not isinstance(iv, int) or iv < 1):
            raise BadRequest(f"aggregate {i}: bad type, func, interval, or deviceFilter")
        if not is_ms(a.get("bucketStart")) or not is_ms(a.get("bucketEnd")) or a["bucketEnd"] <= a["bucketStart"]:
            raise BadRequest(f"aggregate {i}: bucketEnd must be after bucketStart")
        b["aggregates"].append(a)
    for i, a in take(counts["activitySummaryCount"], "activity summary", "activitySummary"):
        if not is_ms(a.get("date")) or a.get("moveMode") not in (None, 0, 1):
            raise BadRequest(f"activity summary {i}: bad date or moveMode")
        if a.get("localDate") is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(a["localDate"])):
            raise BadRequest(f"activity summary {i}: invalid localDate")
        b["activitySummaries"].append(a)
    for _, p in take(counts["profileCount"], "profile", "profile"):
        b["profile"] = p
    for _ in lines:
        raise BadRequest("unexpected trailing line after the declared counts")
    return b


def local_day(a):
    """Upsert key for an activity summary: localDate, else the UTC day of the legacy date."""
    return a.get("localDate") or datetime.fromtimestamp(a["date"] / 1000, timezone.utc).strftime("%Y-%m-%d")


def apply_batch(db, b, user_id):
    """One transaction per batch. A replayed batchID is a no-op; deletions run last."""
    # UUID spelling is case-insensitive; canonicalize identity before SQL comparisons.
    b = copy.deepcopy(b)
    user_id = user_id.lower()
    b["header"]["batchID"] = b["header"]["batchID"].lower()
    for group, field in (("samples", "uuid"), ("deletions", "uuid"),
                         ("routes", "workoutUUID"), ("series", "workoutUUID")):
        for item in b[group]:
            item[field] = item[field].lower()
    h, res, ts = b["header"], dict(ZERO_RESULT), now()
    with db:
        db.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
        if not db.execute("INSERT OR IGNORE INTO batches VALUES (?,?,?,?,?,?,?,?,?)",
                          (h["batchID"], user_id, h.get("deviceID"), h["type"], h.get("reason"),
                           h.get("schemaVersion") or 1, h.get("clientVersion"), h.get("exportedAt"), ts)).rowcount:
            res["duplicates"] = len(b["samples"])  # retried upload: already applied
            return res
        for s in b["samples"]:  # the UUID is the identity; a known UUID is never overwritten
            res["accepted"] += db.execute(
                "INSERT OR IGNORE INTO samples SELECT ?,?,?,?,?,?,?,?,?,?,?,? "
                "WHERE NOT EXISTS (SELECT 1 FROM deletions WHERE uuid=? AND user_id=?)",
                (s["uuid"], user_id, s["type"], s["kind"], s["start"], s.get("end") or s["start"], s.get("value"),
                 s.get("unit"), s.get("category"), s.get("sourceName"), s.get("device"),
                 json.dumps(s, separators=(",", ":")), s["uuid"], user_id)).rowcount
        res["duplicates"] = len(b["samples"]) - res["accepted"]
        for r in b["routes"]:
            res["routePoints"] += db.executemany(
                "INSERT OR IGNORE INTO route_points VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(r["workoutUUID"], p["t"], user_id, p["lat"], p["lon"], p.get("alt"), p.get("hAcc"), p.get("vAcc"),
                  p.get("speed"), p.get("course")) for p in r["points"]]).rowcount
        for s in b["series"]:
            res["seriesPoints"] += db.executemany(
                "INSERT OR IGNORE INTO series_points VALUES (?,?,?,?,?,?)",
                [(s["workoutUUID"], s["type"], p["t"], user_id, p["value"], s.get("unit")) for p in s["points"]]).rowcount
        if b["profile"] is not None:  # a complete snapshot: null or absent fields clear stored values
            p = b["profile"]
            db.execute("INSERT INTO users VALUES (?,?,?,?,?,?) ON CONFLICT (id) DO UPDATE SET name=excluded.name,"
                       " email=excluded.email, date_of_birth_ms=excluded.date_of_birth_ms,"
                       " biological_sex=excluded.biological_sex, updated_at=excluded.updated_at",
                       (user_id, p.get("name"), p.get("email"), p.get("dateOfBirth"), p.get("biologicalSex"), ts))
        for a in b["aggregates"]:  # upsert on the bucket identity; an explicit null clears the value
            db.execute("INSERT INTO aggregates VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO UPDATE SET"
                       " bucket_end_ms=excluded.bucket_end_ms, value=excluded.value, unit=excluded.unit,"
                       " updated_at=excluded.updated_at",
                       (user_id, a["type"], a["func"], a["intervalValue"], a["intervalUnit"], a["deviceFilter"],
                        a["bucketStart"], a["bucketEnd"], a.get("value"), a.get("unit"), ts))
            res["aggregateSamples"] += 1
        for a in b["activitySummaries"]:  # upsert on the local day; every column is overwritten, nulls included
            db.execute("INSERT INTO activity_summaries VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO UPDATE SET"
                       " move_kcal=excluded.move_kcal, move_goal_kcal=excluded.move_goal_kcal,"
                       " exercise_min=excluded.exercise_min, exercise_goal_min=excluded.exercise_goal_min,"
                       " stand_hours=excluded.stand_hours, stand_goal_hours=excluded.stand_goal_hours,"
                       " move_mode=excluded.move_mode, move_time_min=excluded.move_time_min,"
                       " move_time_goal_min=excluded.move_time_goal_min, updated_at=excluded.updated_at",
                       (user_id, local_day(a), a.get("moveKcal"), a.get("moveGoalKcal"), a.get("exerciseMin"),
                        a.get("exerciseGoalMin"), a.get("standHours"), a.get("standGoalHours"), a.get("moveMode"),
                        a.get("moveTimeMin"), a.get("moveTimeGoalMin"), ts))
            res["activitySummaries"] += 1
        for d in b["deletions"]:  # an unknown UUID is a no-op; a deleted workout takes its points along
            res["deleted"] += db.execute("DELETE FROM samples WHERE uuid=? AND user_id=?", (d["uuid"], user_id)).rowcount
            db.execute("DELETE FROM route_points WHERE workout_uuid=? AND user_id=?", (d["uuid"], user_id))
            db.execute("DELETE FROM series_points WHERE workout_uuid=? AND user_id=?", (d["uuid"], user_id))
            db.execute("INSERT OR IGNORE INTO deletions VALUES (?,?,?,?)", (d["uuid"], user_id, d["type"], ts))
    return res


class Handler(BaseHTTPRequestHandler):
    server_version = "puls-sqlite-receiver/1"
    protocol_version = "HTTP/1.1"

    def send_json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        got = self.headers.get("Authorization", "")
        return got.startswith("Bearer ") and hmac.compare_digest(got[7:], self.server.token)

    def unsupported_version(self):
        self.send_json(400, {"error": "unsupported protocol version", "supportedVersions": PROTOCOL_VERSIONS})

    def do_GET(self):
        if self.path == "/healthz":
            return self.send_json(200, {"ok": True})
        if not self.authorized():
            return self.send_json(401, {"error": "unauthorized"})
        if self.path == "/v1/capabilities":
            return self.send_json(200, {"protocolVersions": PROTOCOL_VERSIONS, "features": ["batches", "profile"],
                                        "server": "puls-sqlite-receiver", "version": "1"})
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self.authorized():
            return self.send_json(401, {"error": "unauthorized"})
        if self.path != "/v1/batches":
            return self.send_json(404, {"error": "not found"})
        proto = self.headers.get("X-Puls-Protocol", "").strip()  # absent = legacy client
        if proto and (not proto.isdigit() or int(proto) not in PROTOCOL_VERSIONS):
            return self.unsupported_version()
        user_id = self.headers.get("X-User-ID") or DEFAULT_USER
        if not is_uuid(user_id):
            return self.send_json(400, {"error": "X-User-ID is not a UUID"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self.send_json(400, {"error": "invalid Content-Length"})
        if length < 1:
            return self.send_json(400, {"error": "empty body"})
        if length > MAX_BODY:
            return self.send_json(413, {"error": "body too large"})
        raw = self.rfile.read(length)
        encoding = self.headers.get("Content-Encoding", "identity")
        if encoding == "gzip":
            try:
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(MAX_UNCOMPRESSED + 1)
            except (OSError, EOFError) as e:
                return self.send_json(400, {"error": f"invalid gzip body: {e}"})
            if len(raw) > MAX_UNCOMPRESSED:
                return self.send_json(413, {"error": "decompressed body too large"})
        elif encoding not in ("", "identity"):
            return self.send_json(400, {"error": f"unsupported Content-Encoding: {encoding}"})
        elif len(raw) > MAX_UNCOMPRESSED:
            return self.send_json(413, {"error": "body too large"})
        try:
            batch = parse_batch(raw.decode("utf-8"))
            if proto and batch["header"].get("schemaVersion") not in (None, int(proto)):
                raise UnsupportedVersion("X-Puls-Protocol disagrees with schemaVersion")
        except UnsupportedVersion:
            return self.unsupported_version()
        except (BadRequest, UnicodeDecodeError) as e:
            return self.send_json(400, {"error": str(e)})
        try:
            with self.server.lock:
                result = apply_batch(self.server.db, batch, user_id)
        except self.server.db_error as e:
            self.log_error("insert failed: %s", e)
            return self.send_json(500, {"error": "insert failed"})
        self.send_json(200, result)


def main():
    from sqlcipher3 import dbapi2 as cipher

    token_file = os.environ.get("PULS_TOKEN_FILE")
    key_file = os.environ.get("PULS_KEY_FILE")
    db_path = os.environ.get("PULS_DB")
    if not token_file or not key_file or not db_path:
        sys.exit("PULS_TOKEN_FILE, PULS_KEY_FILE, and PULS_DB are required")
    token = open(token_file, encoding="utf-8").read().strip()
    key = open(key_file, "rb").read()
    if len(token) < 32 or len(key) != 32:
        sys.exit("invalid token or archive key length")
    db = cipher.connect(db_path, check_same_thread=False)
    db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
    if not db.execute("PRAGMA cipher_version").fetchone():
        sys.exit("SQLCipher unavailable")
    db.execute("SELECT count(*) FROM sqlite_master").fetchone()
    db.executescript(SCHEMA)
    # Loopback by default, mirroring the reference stack's INGEST_BIND_ADDR:
    # this receiver has no TLS and no throttling on failed authentications, so
    # reaching it from another machine should be something you ask for, not
    # something you get by running it.
    port = int(os.environ.get("PULS_PORT", "8787"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.token, server.db, server.db_error, server.lock = token, db, cipher.Error, threading.Lock()
    print(f"puls-sqlcipher-receiver listening on 127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
