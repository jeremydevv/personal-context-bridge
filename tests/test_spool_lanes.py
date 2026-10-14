import unittest
from pathlib import Path

from personal_context.cli import spool_path_for


class SpoolLaneTests(unittest.TestCase):
    def test_fast_and_full_jobs_do_not_share_retry_queues(self):
        root = Path('/private/spool')
        for action in ('sync', 'messages-sync', 'notes-sync', 'contacts-sync'):
            self.assertNotEqual(spool_path_for(root, action, 'fast'),
                                spool_path_for(root, action, 'full'))
        self.assertNotEqual(spool_path_for(root, 'mail-fast-sync', 'fast'),
                            spool_path_for(root, 'mail-sync', 'full'))


if __name__ == '__main__':
    unittest.main()
