import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from personal_context import provision_tpm_key


class TpmProvisionTests(unittest.TestCase):
    def test_both_runtime_keys_are_sealed_and_verified_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "archive.key"
            key.write_bytes(b"x" * 32)
            key.chmod(0o600)
            credential_dir = root / "config"
            credential = credential_dir / "archive.cred"
            tunnel_key = root / "tunnel-api.key"
            tunnel_key.write_bytes(b"sk-" + b"t" * 40)
            tunnel_key.chmod(0o600)
            tunnel_credential = credential_dir / "tunnel-api.cred"

            def fake_run(args, **kwargs):
                if args[1] == "encrypt":
                    Path(args[-1]).write_bytes(Path(args[-2]).read_bytes()[::-1])
                    return subprocess.CompletedProcess(args, 0, stdout=b"")
                if args[1] == "decrypt":
                    return subprocess.CompletedProcess(args, 0, stdout=Path(args[-2]).read_bytes()[::-1])
                raise AssertionError("unexpected command")

            with patch.object(provision_tpm_key, "KEY_PATH", key), \
                 patch.object(provision_tpm_key, "CREDENTIAL_DIR", credential_dir), \
                 patch.object(provision_tpm_key, "CREDENTIAL_PATH", credential), \
                 patch.object(provision_tpm_key, "TUNNEL_KEY_PATH", tunnel_key, create=True), \
                 patch.object(provision_tpm_key, "TUNNEL_CREDENTIAL_PATH", tunnel_credential, create=True), \
                 patch.object(provision_tpm_key.os, "access", return_value=True), \
                 patch.object(provision_tpm_key.subprocess, "run", side_effect=fake_run), \
                 patch("sys.stdout", new_callable=io.StringIO):
                provision_tpm_key.main()
            self.assertEqual((b"x" * 32)[::-1], credential.read_bytes())
            self.assertEqual((b"sk-" + b"t" * 40)[::-1], tunnel_credential.read_bytes())
            self.assertEqual(0o600, credential.stat().st_mode & 0o777)
            self.assertEqual(0o600, tunnel_credential.stat().st_mode & 0o777)
            self.assertEqual(0o700, credential_dir.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
