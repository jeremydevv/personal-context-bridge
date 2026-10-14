"""OwnTracks receiver accepts a location once and rejects malformed data."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest

from iphone_context.location_receiver import SCHEMA, parse_event, store_event


class LocationReceiverTest(unittest.TestCase):
    def test_deduplicates_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            db = sqlite3.connect(os.path.join(directory, "test.sqlite3"))
            db.executescript(SCHEMA)
            body = json.dumps({"_type": "location", "tst": 1700000000,
                               "lat": 28.0, "lon": -82.0, "acc": 12}).encode()
            self.assertTrue(store_event(db, body))
            self.assertFalse(store_event(db, body))
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 1)

    def test_invalid_location_is_rejected(self):
        for event in ({"_type": "location", "tst": 1, "lat": 91, "lon": 0},
                      {"_type": "location", "tst": 1, "lat": float("nan"), "lon": 0},
                      {"_type": "location", "tst": "yesterday", "lat": 28, "lon": -82}):
            with self.subTest(event=event), self.assertRaises(ValueError):
                parse_event(json.dumps(event).encode())


if __name__ == "__main__":
    unittest.main()
