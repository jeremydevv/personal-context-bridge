import pytest

from personal_context.saved_video.archive import Archive, build_archive, prune_plaintext
from personal_context.saved_video.pipeline import Pipeline, SavedPolicy, write_json


def test_archive_preserves_media_and_evidence_without_persisted_frames(tmp_path):
    allow = tmp_path / "saved.txt"
    allow.write_text("https://www.instagram.com/p/Fictional_123/\n")
    p = Pipeline(SavedPolicy(allow), tmp_path / "input")
    d = p.path("Fictional_123")
    d.mkdir()
    (d / "media.mp4").write_bytes(b"fictional media")
    write_json(
        d / "manifest.json",
        {
            "id": "Fictional_123",
            "url": p.policy.urls[0],
            "status": "complete",
            "assets": [
                {
                    "media": "media.mp4",
                    "duration": 10,
                    "frames": [{"time": 0, "file": "frames/0.jpg"}],
                    "contact_sheets": [],
                }
            ],
        },
    )
    write_json(
        d / "transcript.json",
        {"segments": [{"start": 0, "end": 1, "text": "example speech"}]},
    )
    write_json(
        d / "ocr.json", {"frames": [{"asset": 0, "time": 0, "text": "example screen"}]}
    )
    key = b"x" * 32
    root = tmp_path / "archive"
    report = build_archive(p, root, key)
    assert report["videos"] == 1
    a = Archive(p.policy, root, key)
    assert len(a.search("example")) == 2
    with a.materialize("Fictional_123") as local:
        assert (
            local.path("Fictional_123") / "media.mp4"
        ).read_bytes() == b"fictional media"
        assert (
            local.inspect("Fictional_123", 0, 1)["segments"][0]["text"]
            == "example speech"
        )
        temporary = local.root
    assert not temporary.exists()
    with pytest.raises(ValueError):
        with a.materialize("NOT_SAVED"):
            pass
    assert b"example speech" not in b"".join(
        x.read_bytes() for x in root.rglob("*") if x.is_file()
    )
    before = {x.name for x in root.rglob("*.blob")}
    build_archive(p, root, key)
    assert before == {x.name for x in root.rglob("*.blob")}
    (d / "media.mp4").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        prune_plaintext(p, a)
    assert d.exists()
    (d / "media.mp4").write_bytes(b"fictional media")
    assert prune_plaintext(p, a)["removed_post_directories"] == 1
    assert not d.exists()
    build_archive(p, root, key)
    assert len(Archive(p.policy, root, key).search("example")) == 2
    assert before == {x.name for x in root.rglob("*.blob")}
    allow.write_text(allow.read_text() + "https://www.instagram.com/p/Fictional_456/\n")
    updated = Pipeline(SavedPolicy(allow), p.root)
    with pytest.raises(ValueError, match="complete"):
        build_archive(updated, root, key)
    assert build_archive(updated, root, key, allow_incomplete=True)["videos"] == 1
    with pytest.raises(ValueError):
        Archive(updated.policy, root, key).entry("Fictional_456")
    blob = next(root.rglob("*.blob"))
    data = bytearray(blob.read_bytes())
    data[40] ^= 1
    blob.write_bytes(data)
    from personal_context.blob_store import BlobStore

    with pytest.raises(ValueError):
        BlobStore(root / "objects", key).read(blob.stem, 512 * 1024 * 1024)
