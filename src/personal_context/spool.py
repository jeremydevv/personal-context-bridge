"""Crash-safe local queue for Mac-to-server sync batches."""

import json
import os
import time
import uuid
from pathlib import Path


class Spool:
    # One bounded collector invocation owns this manifest, never pending older work.
    tracking = None
    app_lifecycle = None
    partial_coverage = False
    produced = set()
    acknowledged = set()

    @classmethod
    def begin_tracking(cls, refresh_id, attempt_id, source):
        cls.tracking = dict(refresh_id=refresh_id, attempt_id=attempt_id, source=source)
        cls.produced, cls.acknowledged = set(), set()
        cls.app_lifecycle = None
        cls.partial_coverage = False

    @classmethod
    def tracking_result(cls, coverage='complete'):
        return {'collection_finished': True, 'coverage': 'partial' if cls.partial_coverage else coverage,
                'batch_ids': sorted(cls.produced), 'acked_batch_ids': sorted(cls.acknowledged)}

    @staticmethod
    def _canvas_partial(value):
        """Retain only a coverage bit from provider metadata, never record contents."""
        if isinstance(value, dict):
            if any(value.get(key) in ('partial', 'unavailable', 'failed')
                   for key in ('status', 'content_status', 'extraction_status')):
                return True
            return any(Spool._canvas_partial(item) for item in value.values())
        if isinstance(value, list):
            return any(Spool._canvas_partial(item) for item in value)
        return False

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
        if self.tracking:
            if self.tracking.get('source') == 'canvas' and any(self._canvas_partial(batch) for batch in batches):
                type(self).partial_coverage = True
            batches = [dict(batch, refresh=dict(self.tracking, batch_id=uuid.uuid4().hex)) for batch in batches]
            self.produced.update(batch['refresh']['batch_id'] for batch in batches)
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
            dirfd = os.open(self.directory, os.O_DIRECTORY)
            try: os.fsync(dirfd)
            finally: os.close(dirfd)
        finally:
            if temporary.exists():
                temporary.unlink()

    def flush(self, deliver):
        sent = 0
        for path in self.pending():
            raw = path.read_bytes()
            result = deliver(raw)
            payload = json.loads(raw)
            batches = payload.get('batches', [payload])
            expected = [b['refresh'] for b in batches if b.get('refresh')]
            if expected:
                acks = result.get('receipts', []) if isinstance(result, dict) else []
                if any(dict(e, committed=True) not in acks for e in expected):
                    raise RuntimeError('archive_acknowledgement_missing')
                if self.tracking:
                    self.acknowledged.update(e['batch_id'] for e in expected if e['attempt_id'] == self.tracking['attempt_id'])
            path.unlink()
            sent += 1
        return sent
