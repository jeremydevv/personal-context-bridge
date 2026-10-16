"""Regressions: expanding URL scope or permitting account requests must fail."""

import pytest
from personal_context.saved_video.pipeline import SavedPolicy, Pipeline


@pytest.fixture
def policy(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("https://www.instagram.com/p/Fictional_123/\n")
    return SavedPolicy(f)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/direct/inbox/",
        "https://www.instagram.com/accounts/login/",
        "https://www.instagram.com/p/Unlisted123/",
        "https://evil.example/p/Fictional_123/",
        "https://www.instagram.com@evil.example/p/Fictional_123/",
        "http://www.instagram.com/p/Fictional_123/",
        "https://www.instagram.com/p/Fictional_123/?next=/direct/inbox/",
    ],
)
def test_rejects_non_saved_input(policy, url):
    with pytest.raises(ValueError):
        policy.authorize(url)


def test_accepts_only_saved_canonical_url(policy):
    assert (
        policy.authorize("https://www.instagram.com/p/Fictional_123/")
        == "Fictional_123"
    )


@pytest.mark.parametrize(
    "method,url",
    [
        ("POST", "https://www.instagram.com/api/v1/media/1/like/"),
        ("GET", "https://www.instagram.com/api/v1/direct_v2/inbox/"),
        ("GET", "https://www.instagram.com/"),
        ("GET", "https://www.instagram.com/p/Unlisted123/"),
        (
            "GET",
            "https://www.instagram.com/api/v1/web/get_ruling_for_content/?content_type=MEDIA&target_id=1",
        ),
        ("GET", "https://evil.example/video.mp4"),
    ],
)
def test_network_scope_blocks_non_saved_reads_and_writes(policy, method, url):
    with pytest.raises(ValueError):
        policy.request(method, url, "Fictional_123")


def test_cdn_read_allowed_but_writes_blocked(policy):
    policy.request(
        "GET", "https://scontent.cdninstagram.com/video.mp4", "Fictional_123"
    )
    with pytest.raises(ValueError):
        policy.request(
            "POST", "https://scontent.cdninstagram.com/video.mp4", "Fictional_123"
        )


def test_search_returns_source_timestamps_and_inspection_checks_range(tmp_path, policy):
    import json

    root = tmp_path / "data"
    video = root / "Fictional_123"
    video.mkdir(parents=True)
    (video / "manifest.json").write_text(
        json.dumps(
            {
                "id": "Fictional_123",
                "url": policy.urls[0],
                "duration": 30,
                "frames": [{"time": 10, "file": "frames/10.jpg"}],
            }
        )
    )
    (video / "transcript.json").write_text(
        json.dumps(
            {"segments": [{"start": 9, "end": 12, "text": "A fictional blue bicycle."}]}
        )
    )
    p = Pipeline(policy, root)
    found = p.search("bicycle")
    assert found[0]["start"] == 9 and found[0]["url"] == policy.urls[0]
    assert p.inspect("Fictional_123", 9, 12)["frames"][0]["time"] == 10
    with pytest.raises(ValueError):
        p.inspect("Unlisted123", 0, 10)
    with pytest.raises(ValueError):
        p.inspect("Fictional_123", 20, 10)
    with pytest.raises(ValueError):
        p.inspect("Fictional_123", -1, 10)


def test_search_finds_visual_text_separately_from_speech(tmp_path, policy):
    import json

    p = Pipeline(policy, tmp_path / "data")
    v = p.path("Fictional_123")
    v.mkdir()
    (v / "manifest.json").write_text(
        json.dumps({"id": "Fictional_123", "url": policy.urls[0], "status": "complete"})
    )
    (v / "ocr.json").write_text(
        json.dumps(
            {"frames": [{"time": 4.5, "asset": 0, "text": "BLUE BICYCLE", "lines": []}]}
        )
    )
    result = p.search("bicycle")
    assert result[0]["modality"] == "screen_text"
    assert result[0]["start"] == 4.5


def test_incomplete_evidence_is_not_reused_as_complete(tmp_path, policy):

    p = Pipeline(policy, tmp_path / "data")
    d = p.path("Fictional_123")
    d.mkdir()
    v = {
        "id": "Fictional_123",
        "url": policy.urls[0],
        "status": "complete",
        "transcription_model": "small",
        "assets": [
            {
                "media": "missing.mp4",
                "frames": [{"file": "missing.jpg", "time": 0}],
                "transcript": "asset-0/transcript.json",
                "contact_sheets": ["missing-sheet.jpg"],
            }
        ],
    }
    assert not p.reusable(v, "small")


def test_carousel_keeps_video_without_trying_to_download_image_slides():
    from personal_context.saved_video.pipeline import video_only_product

    source = {
        "media_type": 8,
        "carousel_media": [{"media_type": 1, "pk": 1}, {"media_type": 2, "pk": 2}],
    }
    result = video_only_product(source)
    assert result["carousel_media"] == [{"media_type": 2, "pk": 2}]
    assert len(source["carousel_media"]) == 2


def test_transport_removes_credentials_and_rechecks_redirect_targets(policy):
    import urllib.request
    from personal_context.saved_video.pipeline import guard_request

    req = urllib.request.Request(
        policy.urls[0],
        headers={"Cookie": "sessionid=fictional", "Authorization": "Bearer fictional"},
    )
    req.add_unredirected_header("Proxy-Authorization", "fictional")
    record = guard_request(policy, req, "Fictional_123")
    assert record["credentials"] is False
    assert not any(
        k.lower() in ("cookie", "authorization", "proxy-authorization")
        for k, v in req.header_items()
    )
    redirect = urllib.request.Request("https://www.instagram.com/direct/inbox/")
    with pytest.raises(ValueError):
        guard_request(policy, redirect, "Fictional_123")
