import tempfile
import unittest
from pathlib import Path

from personal_context.install_tunnel_key import install


class InstallTunnelKeyTests(unittest.TestCase):
    def test_installs_key_privately_without_trailing_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config" / "tunnel-api.key"
            secret = "sk-" + "a" * 50
            install(secret, target)
            self.assertEqual(secret.encode(), target.read_bytes())
            self.assertEqual(0o600, target.stat().st_mode & 0o777)
            self.assertEqual(0o700, target.parent.stat().st_mode & 0o777)

    def test_refuses_to_replace_existing_key_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tunnel-api.key"
            target.write_text("existing")
            with self.assertRaises(FileExistsError):
                install("sk-" + "a" * 50, target)
            self.assertEqual("existing", target.read_text())
            target.unlink()
            target.symlink_to(Path(directory) / "other")
            with self.assertRaises(FileExistsError):
                install("sk-" + "a" * 50, target)

    def test_rejects_invalid_key_without_creating_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tunnel-api.key"
            with self.assertRaises(ValueError):
                install("not-a-runtime-key", target)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
