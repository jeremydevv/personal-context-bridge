import importlib.util
from pathlib import Path
import subprocess
import unittest
import io
import tarfile
import tempfile
import gzip

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "release_check", ROOT / "scripts/check_release.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PublicationBoundaryTests(unittest.TestCase):
    def archive_metadata(self, *, directory=False, global_headers=None, **fields):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fictional.tar.gz'
            with open(path, 'wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed, \
                 tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT,
                              pax_headers=global_headers) as archive:
                info = tarfile.TarInfo('package/folder' if directory else 'package/file.txt')
                if directory:
                    info.type = tarfile.DIRTYPE
                else:
                    info.size = 4
                for key, value in fields.items():
                    setattr(info, key, value)
                archive.addfile(info, None if directory else io.BytesIO(b'demo'))
            return release.tar_metadata_issues(path)

    def test_neutral_archive_metadata_is_allowed(self):
        self.assertEqual([], self.archive_metadata())
        self.assertEqual([], self.archive_metadata(directory=True))
        self.assertEqual([], self.archive_metadata(pax_headers={'mtime': '123.45'}))

    def test_private_archive_owner_fields_and_extensions_are_rejected(self):
        for fields in ({'uname':'fictional-builder'}, {'gname':'fictional-group'},
                       {'uid':1001}, {'gid':1002},
                       {'pax_headers':{'uname':'fictional-builder'}},
                       {'pax_headers':{'uid':'1001'}},
                       {'pax_headers':{'SCHILY.xattr.user.private':'fictional-marker'}},
                       # Effective PAX metadata cannot hide an identifying raw owner.
                       {'uname':'fictional-builder','pax_headers':{'uname':''}}):
            for directory in (False, True):
                with self.subTest(fields=fields,directory=directory):
                    result = self.archive_metadata(directory=directory, **fields)
                    self.assertTrue(result)
                    self.assertNotIn('fictional-builder', str(result))
                    self.assertNotIn('fictional-group', str(result))
                    self.assertNotIn('fictional-marker', str(result))
        self.assertTrue(self.archive_metadata(global_headers={'comment':'fictional-marker'}))

    def test_raw_owner_padding_and_gzip_headers_cannot_hide_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fictional.tar.gz'
            info = tarfile.TarInfo('package/file.txt')
            header = bytearray(info.tobuf(format=tarfile.USTAR_FORMAT))
            header[265:297] = b'\0fictional-builder'.ljust(32, b'\0')
            header[148:156] = b'        '
            header[148:156] = ('%06o\0 ' % sum(header)).encode()
            path.write_bytes(gzip.compress(bytes(header) + b'\0' * 1024, mtime=0))
            self.assertTrue(release.tar_metadata_issues(path))
            neutral = info.tobuf(format=tarfile.USTAR_FORMAT) + b'\0' * 1024
            packed = gzip.compress(neutral, mtime=0)
            # Header comment is discarded by gzip.open but retained in the artifact.
            path.write_bytes(packed[:3] + b'\x10' + packed[4:10] + b'fictional-builder\0' + packed[10:])
            self.assertTrue(release.tar_metadata_issues(path))
            path.write_bytes(packed + gzip.compress(b'', mtime=0))
            self.assertTrue(release.tar_metadata_issues(path))

    def test_runtime_files_are_ignored_and_rejected_even_when_force_added(self):
        paths = [
            "cookies.sqlite-wal",
            "cookies.txt",
            "storage-state.json",
            "saved-video-urls.txt",
            "saved-video-sync.json",
            "saved-video-staging/example.json",
            "saved-videos/object.blob",
            "instagram-profile/cookies.sqlite",
            "private/export.json",
            "media/video.mp4",
            "models/model.onnx",
            "frames/sample.jpg",
        ]
        for path in paths:
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT
                )
                self.assertEqual(0, result.returncode)
                self.assertTrue(release.issues(path, b"fictional private payload"))

    def test_scanner_does_not_echo_sensitive_matching_values(self):
        release.MARKERS.append("fictional-personal-marker")
        try:
            findings = release.issues(
                "example.py", b'value = "fictional-personal-marker"'
            )
            self.assertTrue(findings)
            self.assertNotIn("fictional-personal-marker", str(findings))
        finally:
            release.MARKERS.pop()

    def test_only_reviewed_artwork_bytes_are_allowed(self):
        self.assertEqual(5, len(release.PUBLIC_ARTWORK))
        for name in release.PUBLIC_ARTWORK:
            with self.subTest(name=name):
                data = (ROOT / name).read_bytes()
                self.assertEqual([], release.issues(name, data))
                self.assertTrue(release.issues(name, data + b"altered"))
        self.assertTrue(release.issues("docs/assets/unreviewed.png", b"PNG\x00"))
        self.assertTrue(release.issues("runtime/banner.png", b"PNG\x00"))
