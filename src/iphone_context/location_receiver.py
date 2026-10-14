"""Private OwnTracks HTTP receiver backed by SQLCipher.

Accepts OwnTracks JSON at /pub. A 2xx response acknowledges delivery, so
the write commits before responding. Duplicate retries are harmless.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 65536
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    digest TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    topic TEXT,
    event_ts INTEGER,
    received_ts INTEGER NOT NULL,
    lat REAL,
    lon REAL,
    accuracy REAL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_time ON events(event_ts);
CREATE INDEX IF NOT EXISTS events_by_type_time ON events(event_type, event_ts);
CREATE TABLE IF NOT EXISTS timeline_segments (
    digest TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER NOT NULL,
    lat REAL,
    lon REAL,
    place_id TEXT,
    source TEXT NOT NULL,
    first_import_run TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS timeline_segments_by_time ON timeline_segments(start_ts);
CREATE INDEX IF NOT EXISTS timeline_segments_by_kind_time ON timeline_segments(kind, start_ts);
CREATE TABLE IF NOT EXISTS timeline_imports (
    run_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    imported_ts INTEGER NOT NULL,
    seen_count INTEGER NOT NULL,
    inserted_count INTEGER NOT NULL
);
"""


def parse_event(body: bytes) -> tuple[str, dict]:
    if not body or len(body) > MAX_BODY:
        raise ValueError("invalid body length")
    try:
        event = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(event, dict) or not isinstance(event.get("_type"), str):
        raise ValueError("missing OwnTracks event type")
    event_type = event["_type"]
    ts = event.get("tst")
    if ts is not None and (isinstance(ts, bool) or not isinstance(ts, int) or ts < 0):
        raise ValueError("invalid event timestamp")
    if event_type == "location":
        lat, lon = event.get("lat"), event.get("lon")
        if (isinstance(lat, bool) or not isinstance(lat, (int, float)) or not math.isfinite(lat) or not -90 <= lat <= 90
                or isinstance(lon, bool) or not isinstance(lon, (int, float)) or not math.isfinite(lon) or not -180 <= lon <= 180
                or ts is None):
            raise ValueError("invalid location coordinates or timestamp")
    return event_type, event


def store_event(db, body: bytes) -> bool:
    event_type, event = parse_event(body)
    digest = hashlib.sha256(body).hexdigest()
    with db:
        inserted = db.execute(
            "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?)",
            (digest, event_type, event.get("topic"), event.get("tst"), int(time.time()),
             event.get("lat"), event.get("lon"), event.get("acc"), body.decode("utf-8")),
        ).rowcount
    return bool(inserted)


class Handler(BaseHTTPRequestHandler):
    server_version = "private-owntracks/1"
    protocol_version = "HTTP/1.1"

    def respond(self, status: int, body: bytes = b"[]") -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            user, password = base64.b64decode(header[6:], validate=True).decode().split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return False
        return hmac.compare_digest(user, self.server.username) and hmac.compare_digest(password, self.server.password)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            return self.respond(200, b'{"ok":true}')
        self.respond(404)

    def do_POST(self) -> None:
        if self.path != "/pub":
            return self.respond(404)
        if not self.authorized():
            return self.respond(401)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self.respond(400)
        if not 0 < length <= MAX_BODY:
            return self.respond(413)
        body = self.rfile.read(length)
        try:
            with self.server.lock:
                store_event(self.server.db, body)
        except ValueError:
            return self.respond(400)
        except self.server.db_error as exc:
            self.log_error("store failed: %s", exc)
            return self.respond(500)
        self.respond(200)


def main() -> None:
    from sqlcipher3 import dbapi2 as cipher

    credential_file = os.environ.get("OWNTRACKS_CREDENTIAL_FILE")
    key_file = os.environ.get("OWNTRACKS_KEY_FILE")
    db_path = os.environ.get("OWNTRACKS_DB")
    if not credential_file or not key_file or not db_path:
        sys.exit("OWNTRACKS_CREDENTIAL_FILE, OWNTRACKS_KEY_FILE, and OWNTRACKS_DB are required")
    password = open(credential_file, encoding="utf-8").read().strip()
    key = open(key_file, "rb").read()
    if len(password) < 32 or len(key) != 32:
        sys.exit("invalid credential or archive key length")
    db = cipher.connect(db_path, check_same_thread=False)
    db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
    if not db.execute("PRAGMA cipher_version").fetchone():
        sys.exit("SQLCipher unavailable")
    db.execute("SELECT count(*) FROM sqlite_master").fetchone()
    db.executescript(SCHEMA)
    port = int(os.environ.get("OWNTRACKS_PORT", "8788"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.db, server.db_error, server.lock = db, cipher.Error, threading.Lock()
    server.username, server.password = os.environ.get("OWNTRACKS_USERNAME", "iphone"), password
    print(f"private OwnTracks receiver listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
