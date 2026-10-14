"""Delayed HealthKit uploads must not undo an already received deletion."""

import sqlite3
import sys
import unittest
from pathlib import Path

from iphone_context.health_receiver import SCHEMA, apply_batch


class HealthDeletionOrderTest(unittest.TestCase):
    def test_late_sample_batch_does_not_resurrect_deleted_uuid(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        user_id = "5ea4d000-0000-4000-8000-000000000001"
        sample_id = "ad0f0000-0000-4000-8000-000000000001"
        sample = {"uuid": sample_id, "type": "heart", "kind": "quantity",
                  "start": 1790856000000, "value": 72}

        def batch(batch_id, *, samples=(), deletions=()):
            return {"header": {"batchID": batch_id, "type": "heart"},
                    "samples": list(samples), "deletions": list(deletions),
                    "routes": [], "series": [], "aggregates": [],
                    "activitySummaries": [], "profile": None}

        apply_batch(db, batch("b0000000-0000-4000-8000-000000000001", samples=[sample]), user_id)
        apply_batch(db, batch("b0000000-0000-4000-8000-000000000002",
                              deletions=[{"uuid": sample_id, "type": "heart"}]), user_id)
        late = apply_batch(db, batch("b0000000-0000-4000-8000-000000000003",
                                     samples=[sample]), user_id)

        self.assertEqual(db.execute("SELECT count(*) FROM samples WHERE uuid=?", (sample_id,)).fetchone()[0], 0)
        self.assertEqual(late["accepted"], 0)


if __name__ == "__main__":
    unittest.main()
