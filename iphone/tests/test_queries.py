import sqlite3
import json
import sys
import unittest
from pathlib import Path

from iphone_context.health_receiver import SCHEMA as HEALTH_SCHEMA
from iphone_context.location_receiver import SCHEMA as LOCATION_SCHEMA
from iphone_context.queries import HealthQueries, TravelQueries, epoch_range


class ReadQueriesTest(unittest.TestCase):
    def test_health_activity_days_and_workout_points_are_readable_in_pages(self):
        db = sqlite3.connect(":memory:")
        db.executescript(HEALTH_SCHEMA)
        db.execute("INSERT INTO activity_summaries (user_id,date,move_kcal,exercise_min,stand_hours,updated_at) "
                   "VALUES (?,?,?,?,?,?)", ("u", "2026-10-01", 300, 25, 10, "2026-10-02T00:00:00Z"))
        db.executemany("INSERT INTO route_points (workout_uuid,t_ms,user_id,lat,lon) VALUES (?,?,?,?,?)",
                       [("workout-1", 1000, "u", 1.0, 2.0), ("workout-1", 2000, "u", 1.1, 2.1)])
        db.execute("INSERT INTO series_points (workout_uuid,type,t_ms,user_id,value,unit) "
                   "VALUES (?,?,?,?,?,?)", ("workout-1", "heartRate", 1500, "u", 72, "count/min"))
        q = HealthQueries(db)

        days = q.activity_days("2026-10-01", "2026-10-03")
        self.assertEqual(days["days"][0]["move_kcal"], 300)
        self.assertEqual(days["days"][0]["date"], "2026-10-01")
        self.assertEqual(q.workout_route("workout-1", limit=1, offset=1)["points"][0]["latitude"], 1.1)
        self.assertEqual(q.workout_route("workout-1", limit=1)["total"], 2)
        self.assertEqual(q.workout_series("workout-1")["points"][0]["value"], 72)
        with self.assertRaises(ValueError):
            q.activity_days("2026-10-01", "2028-10-01")
        with self.assertRaises(ValueError):
            q.workout_route("workout-1", offset=-1)

    def test_health_queries_filter_types_and_bound_ranges(self):
        db = sqlite3.connect(":memory:")
        db.executescript(HEALTH_SCHEMA)
        db.execute("INSERT INTO batches (batch_id,user_id,received_at) VALUES ('b','u','2026-10-01T12:00:00Z')")
        db.execute("INSERT INTO samples (uuid,user_id,type,kind,start_ms,end_ms,line) VALUES (?,?,?,?,?,?,?)",
                   ("a", "u", "steps", "quantity", 1790856000000, 1790856000000, "{}"))
        db.execute("INSERT INTO samples (uuid,user_id,type,kind,start_ms,end_ms,line) VALUES (?,?,?,?,?,?,?)",
                   ("b", "u", "heart", "quantity", 1790856000000, 1790856000000, "{}"))
        q = HealthQueries(db)
        self.assertEqual(q.status()["sample_count"], 2)
        rows = q.samples("steps", "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")
        self.assertEqual([r["id"] for r in rows["samples"]], ["a"])
        self.assertEqual(q.samples("steps' OR 1=1 --", "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")["samples"], [])
        with self.assertRaises(ValueError):
            q.samples("steps", "2026-10-01T00:00:00Z", "2027-10-03T00:00:00Z")
        with self.assertRaises(ValueError):
            q.types(101)

    def test_location_queries_only_return_locations(self):
        db = sqlite3.connect(":memory:")
        db.executescript(LOCATION_SCHEMA)
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",
                   ("a" * 64, "location", "phone", 1790856000, 1790856001, 1.5, 2.5, 8.0, json.dumps({"_type": "location"})))
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",
                   ("b" * 64, "transition", "phone", 1790856000, 1790856002, None, None, None, '{}'))
        q = TravelQueries(db)
        self.assertEqual(q.status()["event_count"], 2)
        self.assertEqual(q.status()["location_count"], 1)
        rows = q.locations("2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")
        self.assertEqual(len(rows["locations"]), 1)
        self.assertEqual(q.event("a" * 64)["event"]["_type"], "location")
        with self.assertRaises(ValueError):
            q.event("x")

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            epoch_range("2026-10-01", "2026-10-02T00:00:00Z", milliseconds=False)


if __name__ == "__main__":
    unittest.main()
