"""Mac Voice Memo collection with existing protected spool and SSH transport."""

import json
import subprocess
from .voice_memos_collect import collect_voice_memos, audio_candidates


def sync(config, spool):
    from .cli import deliver_ssh, remote_image_command

    spool.flush(lambda payload: deliver_ssh(config, payload))
    batches, counts = collect_voice_memos()
    for batch in batches:
        spool.enqueue([batch])
        spool.flush(lambda payload: deliver_ssh(config, payload))

    # Stream original audio separately; never base64 it into text records/spool.
    def remote(action, *extra):
        command = remote_image_command(config, "voice-worker", action, *extra)
        return command

    result = subprocess.run(remote("audio-index"), capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError("Voice Memo audio index unavailable")
    known = {r["id"]: r for r in json.loads(result.stdout)["records"]}
    transferred = 0
    for item in audio_candidates():
        target = known.get(item["id"])
        if (
            not target
            or target["archived"]
            or item["bytes"] != target["bytes"]
            or item["mtime_ns"] != target["mtime_ns"]
        ):
            continue
        command = remote(
            "ingest-audio",
            "--record-id",
            item["id"],
            "--sha256",
            target["sha256"],
            "--bytes",
            str(item["bytes"]),
        )
        with item["path"].open("rb") as f:
            result = subprocess.run(command, stdin=f, capture_output=True, timeout=1800)
        if result.returncode:
            raise RuntimeError("Voice Memo audio transfer failed; retry next sync")
        transferred += 1
    return dict(counts, batches=len(batches), audio_transferred=transferred)
