import pytest


@pytest.fixture(autouse=True)
def isolated_video_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("SAVED_VIDEO_ARCHIVE", raising=False)
