import sqlite3
import tempfile
import unittest
from pathlib import Path

from personal_context.store import Store


class ScopeIngestionCostTests(unittest.TestCase):
    def test_retiring_a_scope_does_not_rescan_search_for_each_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "archive.sqlite3")
            try:
                batch = dict(schema=1, source="apple-pim", kind="calendar",
                             scope="other", collected_at="2026-10-22T00:00:00Z",
                             complete=True, records=[dict(id=str(i), title="Fixture", body="Kept")
                                                     for i in range(2500)])
                store.ingest(batch)
                batch = dict(batch, scope="retiring", records=[
                    dict(id="retiring-" + str(i), title="Fixture", body="Removed")
                    for i in range(525)])
                store.ingest(batch)
                callbacks = 0

                def budget():
                    nonlocal callbacks
                    callbacks += 1
                    return int(callbacks > 300)

                store.db.set_progress_handler(budget, 1000)
                try:
                    store.ingest(dict(batch, collected_at="2026-10-22T01:00:00Z", records=[]))
                except sqlite3.OperationalError as exc:
                    self.fail("Scope retirement exhausted its query budget: " + str(exc))
                finally:
                    store.db.set_progress_handler(None, 0)
                self.assertEqual(2500, store.db.execute("SELECT count(*) FROM records_fts").fetchone()[0])
                self.assertEqual(525, store.db.execute("SELECT count(*) FROM records WHERE deleted=1").fetchone()[0])
                self.assertEqual(1050, store.db.execute("SELECT count(*) FROM versions WHERE id LIKE 'retiring-%'").fetchone()[0])
            finally:
                store.close()

    def test_empty_scope_does_not_scan_records_in_other_scopes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "archive.sqlite3")
            try:
                store.db.executemany(
                    """INSERT INTO records
                    (kind,id,source,scope,title,body,payload,digest,deleted,captured_at)
                    VALUES('calendar',?,'apple-pim','other','Fixture','','{}','fixture',0,?)""",
                    ((str(i), "2026-10-22T00:00:00Z") for i in range(2500)),
                )
                store.db.commit()
                callbacks = 0

                def budget():
                    nonlocal callbacks
                    callbacks += 1
                    return int(callbacks > 100)

                # Abort quadratic scope reconciliation independently of wall time.
                store.db.set_progress_handler(budget, 100)
                try:
                    store.ingest(dict(schema=1, source="apple-pim", kind="calendar",
                                      scope="empty", collected_at="2026-10-22T01:00:00Z",
                                      complete=True, records=[]))
                except sqlite3.OperationalError as exc:
                    self.fail("Empty scope exhausted its query budget: " + str(exc))
                finally:
                    store.db.set_progress_handler(None, 0)
                self.assertEqual(2500, store.db.execute(
                    "SELECT count(*) FROM records WHERE deleted=0").fetchone()[0])
                self.assertEqual(0, store.db.execute(
                    "SELECT count FROM syncs WHERE scope='empty'").fetchone()[0])
            finally:
                store.close()
