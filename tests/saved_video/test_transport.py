import io
from email.message import Message
import urllib.request
import urllib.response

import pytest
from personal_context.saved_video import collect_saved as collector


def test_authenticated_redirect_never_sends_cookies_to_another_endpoint(monkeypatch):
    requests = []

    class SyntheticHTTPS(urllib.request.HTTPSHandler):
        def https_open(self, request):
            requests.append(request.full_url)
            assert request.get_header("Cookie") == "fictional-cookie"
            headers = Message()
            headers["Location"] = "https://www.instagram.com/direct/inbox/"
            result = urllib.response.addinfourl(
                io.BytesIO(b""), headers, request.full_url, 302
            )
            result.msg = "Moved"
            return result

    original = urllib.request.build_opener
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *handlers: original(*handlers, SyntheticHTTPS()),
    )
    monkeypatch.setattr(collector, "session_cookie_header", lambda: "fictional-cookie")
    fetch = collector.authenticated_fetcher()
    saved = collector.ENDPOINT + "?include_igtv_preview=false"
    with pytest.raises(collector.CollectionError, match="redirect_blocked"):
        fetch(saved)
    assert requests == [saved]
