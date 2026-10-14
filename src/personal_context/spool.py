"""Crash-safe local queue for Mac-to-server sync batches."""

import json
import os
import time
import uuid
from pathlib import Path


class Spool:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)

    def pending(self):
        return sorted(self.directory.glob("*.json"))

    def enqueue(self, batches):
        batches = list(batches)
        if not batches:
            return
        payload = batches[0] if len(batches) == 1 else {"schema": 1, "batches": batches}
        pending = self.pending()
        newest = pending[-1].stem.split("-", 1)[0] if pending else ""
        floor = int(newest) + 1 if len(newest) == 20 and newest.isdigit() else 0
        name = f"{max(time.time_ns(), floor):020d}-{uuid.uuid4().hex}"
        temporary = self.directory / (name + ".tmp")
        final = self.directory / (name + ".json")
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(final))
        finally:
            if temporary.exists():
                temporary.unlink()

    def flush(self, deliver):
        sent = 0
        for path in self.pending():
            deliver(path.read_bytes())
            path.unlink()
            sent += 1
        return sent
