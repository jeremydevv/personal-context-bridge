"""Synthetic Google Maps phone Timeline import and bounded read checks."""

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from iphone_context.queries import TravelQueries
from iphone_context.timeline_import import HashingLimitedReader, import_stream


def export(*segments):
    return io.BytesIO(json.dumps({"semanticSegments": list(segments),
                                  "rawSignals": []}).encode())


VISIT = {
    "startTime": "2024-05-01T10:00:00Z", "endTime": "2024-05-01T11:00:00Z",
    "visit": {"topCandidate": {"placeId": "place-123",
                               "semanticType": "TYPE_CAFE",
                               "placeLocation": {"latLng": "28.123°, -82.456°"},
                               "probability": 0.85}},
}
ACTIVITY = {
    "startTime": "2024-05-01T11:00:00Z", "endTime": "2024-05-01T12:00:00Z",
    "activity": {"start": {"latLng": "28.123°, -82.456°"},
                 "end": {"latLng": "28.555°, -82.999°"},
                 "distanceMeters": 12000,
                 "topCandidate": {"type": "IN_PASSENGER_VEHICLE"}},
}
PATH = {
    "startTime": "2024-05-01T12:00:00Z", "endTime": "2024-05-01T12:30:00Z",
    "timelinePath": [{"point": "28.555°, -82.999°", "time": "2024-05-01T12:10:00Z"}],
}


class TimelineImportTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")

    def tearDown(self):
        self.db.close()

    def test_import_is_idempotent_and_queryable(self):
        first = import_stream(self.db, export(VISIT, ACTIVITY))
        second = import_stream(self.db, export(VISIT, ACTIVITY))
        self.assertEqual((first["seen"], first["inserted"]), (2, 2))
        self.assertEqual((second["seen"], second["inserted"]), (2, 0))
        self.assertEqual(first["source_sha256"], second["source_sha256"])
        query = TravelQueries(self.db)
        self.assertEqual(query.status()["historical_segment_count"], 2)
        result = query.historical_segments("2024-05-01T00:00:00Z", "2024-05-02T00:00:00Z", "visit")
        self.assertEqual(len(result["segments"]), 1)
        visit = result["segments"][0]
        self.assertEqual((visit["latitude"], visit["longitude"]), (28.123, -82.456))
        self.assertEqual(visit["place_id"], "place-123")
        self.assertEqual(visit["semantic_type"], "TYPE_CAFE")
        activity = query.historical_segments("2024-05-01T00:00:00Z", "2024-05-02T00:00:00Z", "activity")["segments"][0]
        self.assertEqual((activity["activity_type"], activity["distance_m"]),
                         ("IN_PASSENGER_VEHICLE", 12000))
        self.assertEqual(query.historical_segment(visit["id"])["segment"]["visit"]["topCandidate"]["placeId"], "place-123")
        with self.assertRaises(ValueError):
            query.historical_segments("2024-05-01T00:00:00Z", "2024-05-02T00:00:00Z", "visit' OR 1=1 --")

    def test_bad_segment_rolls_back_whole_import(self):
        bad = {**VISIT, "startTime": "yesterday"}
        with self.assertRaises(ValueError):
            import_stream(self.db, export(VISIT, bad))
        self.assertEqual(self.db.execute("SELECT count(*) FROM timeline_segments").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM timeline_imports").fetchone()[0], 0)

    def test_other_export_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no semanticSegments"):
            import_stream(self.db, io.BytesIO(b'{"timelineObjects":[]}'))

    def test_array_variant_and_path_anchor(self):
        source = io.BytesIO(json.dumps([VISIT, ACTIVITY, PATH]).encode())
        self.assertEqual(import_stream(self.db, source)["inserted"], 3)
        rows = TravelQueries(self.db).historical_segments(
            "2024-05-01T00:00:00Z", "2024-05-02T00:00:00Z", "path")
        self.assertEqual(len(rows["segments"]), 1)
        self.assertEqual((rows["segments"][0]["latitude"], rows["segments"][0]["longitude"]),
                         (28.555, -82.999))

    def test_input_limit(self):
        reader = HashingLimitedReader(io.BytesIO(b"12345"), limit=4)
        with self.assertRaises(ValueError):
            reader.read()

    def test_sqlcipher_import_reopens_encrypted_when_available(self):
        try:
            from sqlcipher3 import dbapi2 as cipher
        except ImportError:
            self.skipTest("SQLCipher is installed on ubuntu-box")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "travel.sqlite3")
            key = os.urandom(32)
            db = cipher.connect(path)
            db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
            import_stream(db, export(VISIT, ACTIVITY))
            db.close()
            with open(path, "rb") as encrypted:
                self.assertNotEqual(encrypted.read(16), b"SQLite format 3\x00")
            db = cipher.connect(path)
            db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
            self.assertEqual(TravelQueries(db).status()["historical_segment_count"], 2)
            db.close()


if __name__ == "__main__":
    unittest.main()
