import pytest

from personal_context.saved_video.collect_saved import (
    collect,
    validate_request,
    CollectionError,
    publish,
)


@pytest.mark.parametrize(
    "method,url",
    [
        (
            "POST",
            "https://www.instagram.com/api/v1/feed/saved/posts/?include_igtv_preview=false",
        ),
        ("GET", "https://www.instagram.com/api/v1/direct_v2/inbox/"),
        ("GET", "https://www.instagram.com/api/v1/feed/timeline/"),
        ("GET", "https://www.instagram.com/p/Fictional_123/"),
        ("GET", "https://evil.example/api/v1/feed/saved/posts/"),
        (
            "GET",
            "https://www.instagram.com/api/v1/feed/saved/posts/?include_igtv_preview=false&other=1",
        ),
    ],
)
def test_authenticated_request_gate_rejects_everything_except_saved(method, url):
    with pytest.raises(CollectionError):
        validate_request(method, url)


def test_full_snapshot_filters_video_and_paginates_only_saved():
    pages = iter(
        [
            {
                "status": "ok",
                "items": [
                    {"media": {"code": "Fictional_123", "media_type": 2}},
                    {"media": {"code": "Still_123", "media_type": 1}},
                ],
                "more_available": True,
                "next_max_id": "cursor_1",
            },
            {
                "status": "ok",
                "items": [
                    {
                        "media": {
                            "code": "Carousel_123",
                            "media_type": 8,
                            "carousel_media": [{"media_type": 1}, {"media_type": 2}],
                        }
                    }
                ],
                "more_available": False,
            },
        ]
    )
    requests = []

    def fetch(url):
        validate_request("GET", url)
        requests.append(url)
        return next(pages)

    urls, stats = collect(fetch)
    assert urls == [
        "https://www.instagram.com/p/Fictional_123/",
        "https://www.instagram.com/p/Carousel_123/",
    ]
    assert len(requests) == 2 and "max_id=cursor_1" in requests[1]
    assert stats["saved_entries"] == 3


@pytest.mark.parametrize(
    "page",
    [
        {"status": "fail", "items": [], "more_available": False},
        {"status": "ok", "items": [], "more_available": True},
        {"status": "ok", "items": []},
        {
            "status": "ok",
            "items": [{"media": {"media_type": 2}}],
            "more_available": False,
        },
    ],
)
def test_incomplete_or_ambiguous_snapshot_never_replaces_good_allowlist(tmp_path, page):
    path = tmp_path / "saved.txt"
    path.write_text("https://www.instagram.com/p/Fictional_123/\n")
    with pytest.raises(CollectionError):
        urls, _ = collect(lambda url: page)
        publish(path, urls)
    assert "Fictional_123" in path.read_text()


def test_valid_empty_snapshot_revokes_all_access(tmp_path):
    from personal_context.saved_video.pipeline import SavedPolicy

    path = tmp_path / "saved.txt"
    urls, _ = collect(
        lambda url: {"status": "ok", "items": [], "more_available": False}
    )
    publish(path, urls)
    policy = SavedPolicy(path)
    assert policy.ids == set()
    with pytest.raises(ValueError):
        policy.authorize("https://www.instagram.com/p/Fictional_123/")


def test_repeated_pagination_cursor_stops():
    with pytest.raises(CollectionError):
        collect(
            lambda url: {
                "status": "ok",
                "items": [],
                "more_available": True,
                "next_max_id": "loop",
            }
        )
