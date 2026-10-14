import sqlite3
import tempfile
import unittest
from pathlib import Path

from personal_context.image_archive import collect_image_candidates, collect_attachment_candidates
from personal_context.store import Store
from personal_context.service import QueryService


class ImageArchiveTests(unittest.TestCase):
    def test_collects_only_real_images_inside_messages_attachments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'Attachments'
            root.mkdir()
            picture = root / 'photo.jpg'
            picture.write_bytes(b'fake image bytes')
            outside = Path(directory) / 'outside.jpg'
            outside.write_bytes(b'outside')
            video = root / 'movie.mov'
            video.write_bytes(b'video')
            sticker_root = Path(directory) / 'StickerCache'
            sticker_root.mkdir()
            sticker = sticker_root / 'sticker.png'
            sticker.write_bytes(b'sticker')
            database = Path(directory) / 'chat.db'
            db = sqlite3.connect(database)
            db.executescript('''
                CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY, guid TEXT,
                    filename TEXT, mime_type TEXT, total_bytes INTEGER);
                CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
                INSERT INTO attachment VALUES (1,'image-1','photo.jpg','image/jpeg',16);
                INSERT INTO attachment VALUES (2,'outside','../outside.jpg','image/jpeg',7);
                INSERT INTO attachment VALUES (3,'movie','movie.mov','video/quicktime',5);
                INSERT INTO attachment VALUES (4,'sticker','../StickerCache/sticker.png','image/png',7);
                INSERT INTO message_attachment_join VALUES (1,1);
                INSERT INTO message_attachment_join VALUES (2,1);
                INSERT INTO message_attachment_join VALUES (3,2);
                INSERT INTO message_attachment_join VALUES (4,3);
                INSERT INTO message_attachment_join VALUES (5,4);
            ''')
            db.close()
            candidates = collect_image_candidates(database, root)
            self.assertEqual({'image-1', 'sticker'}, {item['guid'] for item in candidates})
            photo = next(item for item in candidates if item['guid'] == 'image-1')
            self.assertEqual(picture.resolve(), photo['path'])
            self.assertEqual(16, photo['bytes'])
            all_files = collect_attachment_candidates(database, root)
            self.assertEqual({'image-1', 'movie', 'sticker'}, {item['guid'] for item in all_files})

    def test_encrypted_index_metadata_tracks_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Store(Path(directory) / 'archive.sqlite3')
            try:
                archive.upsert_image_attachment('image-1', 'a' * 64, 'image/jpeg',
                                                16, 123, 'b' * 64)
                row = archive.image_attachment('image-1')
                self.assertEqual('a' * 64, row['object_id'])
                self.assertEqual(123, row['source_mtime_ns'])
                archive.upsert_image_attachment('image-1', 'c' * 64, 'image/jpeg',
                                                17, 124, 'd' * 64)
                self.assertEqual(17, archive.image_attachment('image-1')['bytes'])
                self.assertEqual(1, len(archive.image_attachment_index()))
                self.assertEqual(1, len(archive.message_attachment_index()))
                archive.upsert_message_attachment('movie', 'e' * 64, 'video/quicktime',
                                                  5, 125, 'f' * 64)
                self.assertEqual(2, len(archive.message_attachment_index()))
                self.assertEqual('video/quicktime', archive.message_attachment('movie')['mime_type'])
            finally:
                archive.close()
            info = QueryService(Path(directory) / 'archive.sqlite3').message_attachment_info('movie')
            self.assertEqual('video/quicktime', info['attachment']['mime_type'])
            self.assertNotIn('object_id', info['attachment'])


if __name__ == '__main__':
    unittest.main()
