"""Mac LaunchAgent entrypoint for encrypted sync and off-host backup."""

import fcntl
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .cli import load_config


CONFIG_DIR = Path(os.environ.get("PERSONAL_CONTEXT_CONFIG_DIR", Path.home() / ".config/personal-context-bridge"))
DATA_DIR = Path(os.environ.get("PERSONAL_CONTEXT_DATA_DIR", Path.home() / ".local/share/personal-context-bridge"))
KEY_PATH = Path(os.environ.get("PERSONAL_CONTEXT_KEY_FILE", CONFIG_DIR / "archive.key"))
TUNNEL_KEY_PATH = CONFIG_DIR / "tunnel-api.key"
SERVER_KEY_PATH = os.environ.get("PERSONAL_CONTEXT_REMOTE_KEY_FILE", "/run/personal-context-bridge/archive.key")
SERVER_TUNNEL_KEY_PATH = os.environ.get("PERSONAL_CONTEXT_REMOTE_TUNNEL_KEY_FILE", "/run/personal-context-bridge/tunnel.key")
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1"]
BACKUP_MAX_TOTAL_BYTES = 20 * 1024**3
BACKUP_MIN_FREE_BYTES = 8 * 1024**3
BACKUP_TRANSFER_TIMEOUT = 8 * 3600
BLOB_BACKUP_DIR = DATA_DIR / "blob-backup"
TUNNEL_SERVICES = ("personal-context-tunnel.service",
                   "personal-context-calendar-tunnel.service",
                   "personal-context-reminder-tunnel.service",
                   "personal-context-contact-tunnel.service",
                   "personal-context-mail-tunnel.service",
                   "personal-context-message-tunnel.service",
                   "personal-context-note-tunnel.service")


def lock_path_for(data_dir, fast):
    return Path(data_dir) / ("sync-fast.lock" if fast else "sync.lock")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prune_backups(directory, incoming_bytes=0, max_copies=7,
                  max_total_bytes=BACKUP_MAX_TOTAL_BYTES,
                  min_free_bytes=BACKUP_MIN_FREE_BYTES):
    """Keep at least one verified copy while making room for the next transfer."""
    directory = Path(directory)
    backups = sorted(directory.glob("*.sqlite3"))
    target_count = max_copies - (1 if incoming_bytes else 0)
    while len(backups) > 1 and (
            len(backups) > target_count
            or sum(path.stat().st_size for path in backups) + incoming_bytes > max_total_bytes
            or (incoming_bytes and shutil.disk_usage(directory).free < incoming_bytes + min_free_bytes)):
        backups.pop(0).unlink()
    if incoming_bytes and shutil.disk_usage(directory).free < incoming_bytes + min_free_bytes:
        raise RuntimeError("not enough Mac free space for a new encrypted backup")


def run(command, timeout=3600, **kwargs):
    result = subprocess.run(command, capture_output=True, timeout=timeout, **kwargs)
    if result.returncode:
        raise RuntimeError("command failed: " + command[0] + ": " + result.stderr.decode(errors="replace")[-500:])
    return result.stdout.decode(errors="replace").strip()


def mirror_encrypted_blobs(host, remote, verify=False, run_command=run, remote_data_dir=None):
    """Keep an off-host copy of immutable ciphertext blobs on the FileVault Mac."""
    remote_data_dir = Path(remote_data_dir or remote / "data")
    if BLOB_BACKUP_DIR.is_symlink():
        raise RuntimeError("blob backup directory cannot be a symlink")
    BLOB_BACKUP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    BLOB_BACKUP_DIR.chmod(0o700)
    lock_path = DATA_DIR / "blob-backup.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if any(path.is_symlink() for path in BLOB_BACKUP_DIR.rglob("*")):
            raise RuntimeError("blob backup contains a symlink")
        source_dir = str(remote_data_dir / "blobs")
        source = host + ":" + source_dir + "/"
        destination = str(BLOB_BACKUP_DIR) + "/"
        remote_size = run_command(["ssh", *SSH_OPTIONS, host,
                                   "du -sk " + shlex.quote(source_dir)]).split()[0]
        required = int(remote_size) * 1024 + BACKUP_MIN_FREE_BYTES
        if shutil.disk_usage(BLOB_BACKUP_DIR).free < required:
            raise RuntimeError("not enough Mac free space for encrypted blob backup")
        common = ["rsync", "-a", "--safe-links", "--chmod=Fu=rw,Fgo=,Du=rwx,Dgo="]
        transfer = common + (["--checksum"] if verify else []) + [source, destination]
        run_command(transfer, timeout=BACKUP_TRANSFER_TIMEOUT)
        if verify:
            pending = run_command(common + ["--checksum", "--dry-run", "--itemize-changes",
                                            source, destination], timeout=BACKUP_TRANSFER_TIMEOUT)
            if pending:
                raise RuntimeError("encrypted blob backup checksum comparison failed")
        if any(path.is_symlink() for path in BLOB_BACKUP_DIR.rglob("*")):
            raise RuntimeError("blob backup contains a symlink")
        index_command = ("cd " + shlex.quote(str(remote)) + " && PERSONAL_CONTEXT_KEY_FILE="
                         + shlex.quote(SERVER_KEY_PATH) + " .venv/bin/python -m personal_context.cli "
                         "attachment-index --db " + shlex.quote(str(remote_data_dir / "context.sqlite3")))
        attachments = json.loads(run_command(["ssh", *SSH_OPTIONS, host, index_command]))["attachments"]
        for attachment in attachments:
            object_id = attachment["object_id"]
            if not isinstance(object_id, str) or not re.fullmatch(r"[0-9a-f]{64}", object_id):
                raise RuntimeError("invalid object ID in Messages attachment index")
            if not (BLOB_BACKUP_DIR / object_id[:2] / (object_id + ".blob")).is_file():
                raise RuntimeError("encrypted blob backup lacks an indexed Messages file")
        return {"encrypted_blob_backup": str(BLOB_BACKUP_DIR), "verified": verify,
                "indexed_attachments": len(attachments)}


def sync_optional_sources(config, config_path, env, run_command,
                          include_mail=True, include_attachments=False):
    errors = []
    if config.get("all_contacts"):
        try:
            print(run_command([sys.executable, "-m", "personal_context.cli", "contacts-sync",
                               "--config", str(config_path)], env=env))
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append("Contacts: " + str(exc))
    if config.get("all_messages"):
        typedstream_site = Path(sys.prefix) / ("lib/python%d.%d/site-packages" % sys.version_info[:2])
        if not (typedstream_site / "typedstream").is_dir():
            errors.append("Messages decoder is missing")
        else:
            try:
                messages_env = dict(env, PYTHONPATH=env["PYTHONPATH"] + ":" + str(typedstream_site))
                print(run_command([sys.executable, "-m", "personal_context.cli", "messages-sync",
                                   "--config", str(config_path)], env=messages_env))
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                errors.append("Messages: " + str(exc))
        if include_attachments:
            try:
                print(run_command([sys.executable, "-m", "personal_context.cli", "attachment-sync",
                                   "--config", str(config_path), "--limit", "50"],
                                  env=env, timeout=3600))
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                errors.append("Messages attachments: " + str(exc))
    if config.get("all_voice_memos"):
        try:
            print(run_command([sys.executable, "-m", "personal_context.cli", "voice-memos-sync",
                               "--config", str(config_path)], env=env, timeout=3600))
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append("Voice Memos: " + str(exc))
    if config.get("all_notes"):
        try:
            print(run_command([sys.executable, "-m", "personal_context.cli", "notes-sync",
                               "--config", str(config_path)], env=env))
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append("Notes: " + str(exc))
    if include_mail and (config.get("all_mailboxes") or config.get("mailbox_urls")):
        try:
            print(run_command([sys.executable, "-m", "personal_context.cli", "mail-sync",
                               "--config", str(config_path)], env=env, timeout=8 * 3600))
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append("Mail: " + str(exc))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="recent changes without a full backup")
    args = parser.parse_args(argv)
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    DATA_DIR.chmod(0o700)
    lock_path = lock_path_for(DATA_DIR, args.fast)
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("sync already running")
            return 0
        config_path = CONFIG_DIR / "config.json"
        config = load_config(config_path)
        if KEY_PATH.is_symlink() or KEY_PATH.stat().st_mode & 0o077:
            raise RuntimeError("archive key file is not private")
        key = KEY_PATH.read_bytes()
        if len(key) != 32:
            raise RuntimeError("archive key has invalid length")
        host = config["remote_host"]
        remote = Path(config["remote_project"])
        remote_data_dir = Path(config.get("remote_data_dir", str(remote / "data")))
        run(["ssh", *SSH_OPTIONS, host,
             "umask 077; cat > " + shlex.quote(SERVER_KEY_PATH) + "; chmod 600 " + shlex.quote(SERVER_KEY_PATH)], input=key)
        if TUNNEL_KEY_PATH.is_file():
            if TUNNEL_KEY_PATH.is_symlink() or TUNNEL_KEY_PATH.stat().st_mode & 0o077:
                raise RuntimeError("tunnel key file is not private")
            tunnel_key = TUNNEL_KEY_PATH.read_bytes().strip()
            if not tunnel_key.startswith(b"sk-") or len(tunnel_key) < 40:
                raise RuntimeError("tunnel key file is invalid")
            run(["ssh", *SSH_OPTIONS, host,
                 "umask 077; cat > " + shlex.quote(SERVER_TUNNEL_KEY_PATH) + "; chmod 600 " + shlex.quote(SERVER_TUNNEL_KEY_PATH)],
                input=tunnel_key)
            for service in TUNNEL_SERVICES:
                run(["ssh", *SSH_OPTIONS, host, "systemctl --user start " + service])
        project_root = Path(__file__).resolve().parents[2]
        env = dict(os.environ, PYTHONPATH=str(project_root / "src"),
                   PERSONAL_CONTEXT_SYNC_LANE="fast" if args.fast else "full",
                   PATH=str(Path.home() / ".local/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
        sync_output = run([sys.executable, "-m", "personal_context.cli", "fast-sync" if args.fast else "sync",
                           "--config", str(config_path)], env=env)
        print(sync_output)
        if args.fast:
            source_errors = sync_optional_sources(config, config_path, env, run,
                                                  include_mail=False, include_attachments=True)
            if config.get("all_messages"):
                try:
                    print(json.dumps(mirror_encrypted_blobs(host, remote, run_command=run, remote_data_dir=remote_data_dir)))
                except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
                    source_errors.append("Messages blob backup: " + str(exc))
            if config.get("all_mailboxes") or config.get("mailbox_urls"):
                try:
                    print(run([sys.executable, "-m", "personal_context.cli", "mail-fast-sync",
                               "--config", str(config_path)], env=env, timeout=900))
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    source_errors.append("Mail: " + str(exc))
            if source_errors:
                raise RuntimeError("Fast Apple sync failed: " + "; ".join(source_errors))
            return 0
        source_errors = sync_optional_sources(config, config_path, env, run)
        staging_name = "backup-" + uuid.uuid4().hex + ".sqlite3"
        staging = remote_data_dir / staging_name
        remote_command = ("cd " + shlex.quote(str(remote)) + " && PERSONAL_CONTEXT_KEY_FILE=" + shlex.quote(SERVER_KEY_PATH) +
                          " .venv/bin/python -m personal_context.cli backup --db " + shlex.quote(str(remote_data_dir / "context.sqlite3")) + " --output " + shlex.quote(str(staging)))
        temporary = None
        try:
            backup_result = json.loads(run(["ssh", *SSH_OPTIONS, host, remote_command]))
            if (backup_result.get("ok") is not True
                    or not isinstance(backup_result.get("bytes"), int)
                    or backup_result["bytes"] <= 0):
                raise RuntimeError("remote encrypted backup did not report a valid size")
            print(json.dumps(backup_result))
            backup_dir = DATA_DIR / "backups"
            backup_dir.mkdir(mode=0o700, exist_ok=True)
            backup_dir.chmod(0o700)
            prune_backups(backup_dir, incoming_bytes=backup_result["bytes"])
            destination = backup_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".sqlite3")
            temporary = destination.with_suffix(".tmp")
            run(["scp", *SSH_OPTIONS, host + ":" + str(staging), str(temporary)],
                timeout=BACKUP_TRANSFER_TIMEOUT)
            temporary.chmod(0o600)
            local_digest = sha256_file(temporary)
            remote_digest = run(["ssh", *SSH_OPTIONS, host, "sha256sum " + str(staging)]).split()[0]
            if local_digest != remote_digest:
                raise RuntimeError("backup transfer checksum mismatch")
            os.replace(temporary, destination)
            print(json.dumps({"backup": str(destination), "bytes": destination.stat().st_size}))
            prune_backups(backup_dir)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            subprocess.run(["ssh", *SSH_OPTIONS, host, "rm -f " + shlex.quote(str(staging))],
                           capture_output=True, timeout=30)
        if config.get("all_messages"):
            try:
                print(json.dumps(mirror_encrypted_blobs(host, remote, verify=True,
                                                      run_command=run, remote_data_dir=remote_data_dir)))
            except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
                source_errors.append("Messages blob backup: " + str(exc))
        if source_errors:
            raise RuntimeError("Apple source sync failed after archive backup: " + "; ".join(source_errors))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
