"""Authenticated URL collection: GET only the exact Saved-list endpoint.

Never download media, visit posts, follow redirects or persist session cookies.
The anonymous media processor runs only after this process exits.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from .pipeline import DEFAULT_ALLOWLIST

ENDPOINT = "https://www.instagram.com/api/v1/feed/saved/posts/"
PROFILE = Path(
    os.environ.get(
        "SAVED_VIDEO_INSTAGRAM_PROFILE",
        Path.home() / ".local/share/personal-context-bridge/instagram-profile",
    )
)
MAX_RESPONSE = 8 * 1024 * 1024
MAX_PAGES = 100
CODE = re.compile(r"[A-Za-z0-9_-]{3,64}\Z")
CURSOR = re.compile(r"[A-Za-z0-9_:=|.\-]{1,2048}\Z")


class CollectionError(Exception):
    def __init__(self, reason, cooldown=3600):
        self.reason = reason
        self.cooldown = cooldown
        super().__init__(reason)


def validate_request(method, url):
    u = urllib.parse.urlsplit(url)
    if (
        method != "GET"
        or u.scheme != "https"
        or u.netloc != "www.instagram.com"
        or u.path != "/api/v1/feed/saved/posts/"
        or u.fragment
    ):
        raise CollectionError("request_scope_rejected")
    q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    if q.get("include_igtv_preview") != ["false"] or set(q) - {
        "include_igtv_preview",
        "max_id",
    }:
        raise CollectionError("request_query_rejected")
    if "max_id" in q and (
        len(q["max_id"]) != 1 or not CURSOR.fullmatch(q["max_id"][0])
    ):
        raise CollectionError("pagination_cursor_rejected")


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CollectionError(
            "redirect_blocked_authentication_may_be_required", 12 * 3600
        )


class SavedGate(urllib.request.BaseHandler):
    handler_order = 100

    def https_request(self, req):
        validate_request(req.get_method(), req.full_url)
        if req.data is not None:
            raise CollectionError("request_body_rejected")
        return req

    http_request = https_request


def session_cookie_header():
    """Read only relevant Instagram cookies from a private tmpfs DB snapshot.

    Firefox can hold an exclusive SQLite lock. Copy its dedicated cookie DB and
    WAL without touching the original; SQLite recovers only this temporary copy.
    No cookies or response bodies are logged or retained.
    """
    source = PROFILE / "cookies.sqlite"
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/" + str(os.getuid())))
    try:
        with tempfile.TemporaryDirectory(
            prefix="saved-cookie-snapshot-", dir=runtime
        ) as tmp:
            for suffix in ("", "-wal"):
                path = Path(str(source) + suffix)
                if path.exists():
                    if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
                        raise CollectionError("unsafe_cookie_database")
                    dest = Path(tmp) / ("cookies.sqlite" + suffix)
                    shutil.copyfile(path, dest)
                    dest.chmod(0o600)
            with sqlite3.connect(str(Path(tmp) / "cookies.sqlite")) as db:
                db.execute("PRAGMA query_only=ON")
                rows = db.execute(
                    "SELECT name,value,expiry FROM moz_cookies WHERE host IN ('.instagram.com','www.instagram.com','instagram.com') AND path='/' AND name IN ('sessionid','csrftoken','ds_user_id','mid','ig_did','rur')"
                ).fetchall()
    except (OSError, sqlite3.Error):
        raise CollectionError("session_unavailable", 12 * 3600) from None
    cookies = {name: value for name, value, expiry in rows if expiry > time.time()}
    if not cookies.get("sessionid"):
        raise CollectionError("sign_in_required", 12 * 3600)
    if any("\r" in v or "\n" in v or ";" in v for v in cookies.values()):
        raise CollectionError("invalid_session_cookie", 12 * 3600)
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def authenticated_fetcher():
    cookie = session_cookie_header()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirects(), SavedGate()
    )

    def fetch(url):
        validate_request("GET", url)
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Cookie": cookie,
                "X-IG-App-ID": "936619743392459",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0",
                "Accept": "application/json",
                "Referer": "https://www.instagram.com/",
            },
        )
        try:
            with opener.open(req, timeout=30) as response:
                data = response.read(MAX_RESPONSE + 1)
                if len(data) > MAX_RESPONSE:
                    raise CollectionError("response_too_large")
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    delay = max(
                        3600, min(86400, int(e.headers.get("Retry-After", "3600")))
                    )
                except ValueError:
                    delay = 3600
                raise CollectionError("rate_limited", delay) from None
            if e.code in (401, 403):
                raise CollectionError("sign_in_or_review_required", 12 * 3600) from None
            raise CollectionError("saved_endpoint_http_error") from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise CollectionError("saved_endpoint_unavailable_or_non_json") from None

    return fetch


def collect(fetch):
    urls = []
    cursors = set()
    cursor = None
    entries = 0
    for page in range(MAX_PAGES):
        query = {"include_igtv_preview": "false"}
        if cursor:
            query["max_id"] = cursor
        url = ENDPOINT + "?" + urllib.parse.urlencode(query)
        validate_request("GET", url)
        data = fetch(url)
        if (
            not isinstance(data, dict)
            or data.get("status") != "ok"
            or not isinstance(data.get("items"), list)
            or type(data.get("more_available")) is not bool
        ):
            raise CollectionError("saved_response_schema_changed")
        entries += len(data["items"])
        for item in data["items"]:
            if not isinstance(item, dict):
                raise CollectionError("saved_item_schema_changed")
            media = item.get("media", item)
            if not isinstance(media, dict) or media.get("media_type") not in (1, 2, 8):
                raise CollectionError("saved_media_schema_changed")
            carousel = media.get("carousel_media", [])
            if not isinstance(carousel, list) or any(
                not isinstance(m, dict) for m in carousel
            ):
                raise CollectionError("saved_carousel_schema_changed")
            if media["media_type"] == 2 or any(
                m.get("media_type") == 2 for m in carousel
            ):
                code = media.get("code")
                if not isinstance(code, str) or not CODE.fullmatch(code):
                    raise CollectionError("saved_video_code_missing_or_invalid")
                urls.append("https://www.instagram.com/p/" + code + "/")
        if not data["more_available"]:
            return list(dict.fromkeys(urls)), {
                "saved_entries": entries,
                "saved_pages": page + 1,
                "request_method": "GET",
                "endpoint": "/api/v1/feed/saved/posts/",
            }
        cursor = data.get("next_max_id")
        if (
            not isinstance(cursor, str)
            or not CURSOR.fullmatch(cursor)
            or cursor in cursors
        ):
            raise CollectionError("saved_pagination_incomplete")
        cursors.add(cursor)
        time.sleep(1)
    raise CollectionError("saved_page_limit_reached")


def publish(path, urls):
    path = Path(path)
    if path.is_symlink():
        raise CollectionError("unsafe_allowlist")
    data = "".join(url + "\n" for url in urls)
    # A successful no-change check preserves the snapshot file and avoids churn.
    if path.exists() and path.read_text() == data:
        return
    fd, name = tempfile.mkstemp(prefix=".saved-urls-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    os.umask(0o077)
    try:
        previous = (
            set(DEFAULT_ALLOWLIST.read_text().splitlines())
            if DEFAULT_ALLOWLIST.exists()
            else set()
        )
        urls, stats = collect(authenticated_fetcher())
        publish(DEFAULT_ALLOWLIST, urls)
        print(
            json.dumps(
                {
                    "ok": True,
                    **stats,
                    "saved_videos": len(urls),
                    "new_videos": len(set(urls) - previous),
                    "removed_videos": len(previous - set(urls)),
                    "allowlist_sha256": hashlib.sha256(
                        DEFAULT_ALLOWLIST.read_bytes()
                    ).hexdigest(),
                }
            )
        )
    except CollectionError as e:
        print(
            json.dumps(
                {"ok": False, "reason": e.reason, "cooldown_seconds": e.cooldown}
            )
        )
        raise SystemExit(1)
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "collector_internal_error",
                    "cooldown_seconds": 3600,
                }
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
