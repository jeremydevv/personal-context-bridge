"""Install a tunnel runtime key from a hidden local prompt, without shell history."""

import getpass
import os
import sys
from pathlib import Path


DEFAULT_PATH = Path.home() / ".config/personal-context-bridge/tunnel-api.key"


def install(secret, target=DEFAULT_PATH):
    secret = secret.strip()
    if not secret.startswith("sk-") or len(secret) < 40 or not secret.isascii() or any(c.isspace() for c in secret):
        raise ValueError("invalid tunnel runtime key format")
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("tunnel runtime key already exists; inspect it before replacing")
    parent = target.parent
    if parent.is_symlink():
        raise ValueError("tunnel key directory must not be a symlink")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent.chmod(0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(secret.encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        target.chmod(0o600)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def main():
    try:
        secret = getpass.getpass("Paste the restricted tunnel runtime key (hidden): ")
        install(secret)
    except (ValueError, FileExistsError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Saved private tunnel runtime key to " + str(DEFAULT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
