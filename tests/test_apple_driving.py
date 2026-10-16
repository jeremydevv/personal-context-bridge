import sqlite3
import unittest


class DrivingTests(unittest.TestCase):
    def test_origin_must_be_recent_accurate_and_not_from_the_future(self):
        from personal_context.apple_driving import fresh_location
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE events (event_type TEXT, event_ts REAL, lat REAL, lon REAL, accuracy REAL)')
        for observed, accuracy, acceptable in [(990, 20, True), (600, 20, False), (1040, 20, False), (990, 1000, False)]:
            db.execute('DELETE FROM events')
            db.execute('INSERT INTO events VALUES (?,?,?,?,?)', ('location', observed, 37.3, -122.0, accuracy))
            if acceptable:
                result = fresh_location(db, now=1000)
                self.assertEqual(result['latitude'], 37.3)
                self.assertEqual(result['age_seconds'], 10)
            else:
                with self.assertRaises(ValueError): fresh_location(db, now=1000)
