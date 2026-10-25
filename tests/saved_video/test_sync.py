import json
from types import SimpleNamespace

from personal_context.saved_video import sync_saved as sync


def test_sync_separates_credentials_and_skips_processing_unchanged_snapshot(
    tmp_path, monkeypatch
):
    state = tmp_path / "state.json"
    data = tmp_path / "staging"
    data.mkdir()
    monkeypatch.setattr(sync, "STATE", state)
    monkeypatch.setattr(sync, "DEFAULT_DATA", data)
    monkeypatch.setenv("COOKIE", "fictional-private-cookie")
    calls = []

    def child(args, **kwargs):
        assert "COOKIE" not in kwargs["env"]
        calls.append(args)
        if args[-1].endswith("collect_saved"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"ok": True, "allowlist_sha256": "fictional-digest"}),
            )
        assert len(calls) == 2
        (data / "run-report.json").write_text(
            json.dumps({"failed": 0, "total": 1, "complete": 1,
                        "allowlist_sha256": "fictional-digest"})
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sync.subprocess, "run", child)
    sync.run()
    assert json.loads(state.read_text())["result"] == "complete"
    sync.run()
    assert json.loads(state.read_text())["result"] == "unchanged"
    assert len(calls) == 3  # one initial collector+processor, one collector only


def test_collector_failure_preserves_processing_and_obeys_cooldown(
    tmp_path, monkeypatch
):
    state = tmp_path / "state.json"
    monkeypatch.setattr(sync, "STATE", state)
    calls = []

    def child(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {"ok": False, "reason": "rate_limited", "cooldown_seconds": 3600}
            ),
        )

    monkeypatch.setattr(sync.subprocess, "run", child)
    sync.run()
    sync.run()
    assert len(calls) == 1
    assert json.loads(state.read_text())["result"] == "collection_cooldown"
