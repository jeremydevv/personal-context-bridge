"""Seal the already-provisioned archive key to Ubuntu's TPM2 for unattended reboot."""

import os
import subprocess
from pathlib import Path


KEY_PATH = Path(os.environ.get("PERSONAL_CONTEXT_REMOTE_KEY_FILE", "/run/personal-context-bridge/archive.key"))
TUNNEL_KEY_PATH = Path(os.environ.get("PERSONAL_CONTEXT_REMOTE_TUNNEL_KEY_FILE", "/run/personal-context-bridge/tunnel.key"))
CREDENTIAL_DIR = Path.home() / ".config/personal-context-bridge"
CREDENTIAL_PATH = CREDENTIAL_DIR / "archive.cred"
TUNNEL_CREDENTIAL_PATH = CREDENTIAL_DIR / "tunnel-api.cred"
TPM_DEVICE = Path("/dev/tpmrm0")


def main():
    if not os.access(TPM_DEVICE, os.R_OK | os.W_OK):
        raise RuntimeError("TPM2 device access is required; add the service account to group tss and reconnect")
    keys = (
        (KEY_PATH, CREDENTIAL_PATH, "archive.key"),
        (TUNNEL_KEY_PATH, TUNNEL_CREDENTIAL_PATH, "tunnel-api.key"),
    )
    for key_path, credential_path, name in keys:
        if key_path.is_symlink() or not key_path.is_file() or key_path.stat().st_mode & 0o077:
            raise RuntimeError("a private " + name + " must already be provisioned in user runtime storage")
        value = key_path.read_bytes()
        if name == "archive.key" and len(value) != 32:
            raise RuntimeError("archive key has invalid length")
        if name == "tunnel-api.key" and (not value.startswith(b"sk-") or len(value) < 40):
            raise RuntimeError("tunnel API key has invalid length or format")
        if credential_path.exists() or credential_path.is_symlink():
            raise RuntimeError("TPM2 credential already exists: " + credential_path.name)
    CREDENTIAL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    CREDENTIAL_DIR.chmod(0o700)
    staged = []
    try:
        for key_path, credential_path, name in keys:
            temporary = CREDENTIAL_DIR / ("." + name + "-" + str(os.getpid()) + ".cred")
            staged.append((temporary, credential_path))
            subprocess.run([
                "systemd-creds", "encrypt", "--with-key=tpm2", "--tpm2-pcrs=7",
                "--name=" + name, str(key_path), str(temporary),
            ], check=True, capture_output=True, timeout=90)
            temporary.chmod(0o600)
            decrypted = subprocess.run([
                "systemd-creds", "decrypt", "--name=" + name, str(temporary), "-",
            ], check=True, capture_output=True, timeout=90).stdout
            if decrypted != key_path.read_bytes():
                raise RuntimeError("TPM2 credential verification failed for " + name)
        for temporary, credential_path in staged:
            os.replace(temporary, credential_path)
        print("TPM2 archive and tunnel credentials sealed and verified")
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
