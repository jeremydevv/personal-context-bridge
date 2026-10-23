import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "release_check", ROOT / "scripts/check_release.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PublicationBoundaryTests(unittest.TestCase):
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
