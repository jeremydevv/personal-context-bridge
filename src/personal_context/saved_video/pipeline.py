"""Local pipeline: only allowlisted Saved URLs; anonymous read-only downloads."""

from __future__ import annotations
import argparse, functools, hashlib, json, math, os, re, time
from pathlib import Path
import urllib.parse
import urllib.request

DEFAULT_ALLOWLIST = Path(
    os.environ.get(
        "SAVED_VIDEO_ALLOWLIST",
        Path.home() / ".local/state/personal-context-bridge/saved-video-urls.txt",
    )
)
DEFAULT_DATA = Path(
    os.environ.get(
        "SAVED_VIDEO_DATA",
        Path.home() / ".local/share/personal-context-bridge/saved-video-staging",
    )
)
import shutil

FFMPEG = os.environ.get("SAVED_VIDEO_FFMPEG") or shutil.which("ffmpeg")
URL_RE = re.compile(r"https://www\.instagram\.com/p/([A-Za-z0-9_-]{3,64})/")


@functools.lru_cache(maxsize=1)
def ocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)


def read_screen_text(path):
    result, _ = ocr_engine()(str(path))
    return [
        {"text": r[1], "confidence": float(r[2]), "box": r[0]} for r in (result or [])
    ]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as f:
        os.chmod(temp, 0o600)
        json.dump(data, f, indent=2, ensure_ascii=False)
    temp.replace(path)


class SavedPolicy:
    def __init__(self, allowlist):
        self.urls = list(
            dict.fromkeys(
                x.strip() for x in Path(allowlist).read_text().splitlines() if x.strip()
            )
        )
        if any(not URL_RE.fullmatch(u) for u in self.urls):
            raise ValueError("Allowlist must contain canonical Saved post URLs only")
        self.ids = {URL_RE.fullmatch(u)[1] for u in self.urls}
        self.digest = hashlib.sha256(("\n".join(self.urls) + "\n").encode()).hexdigest()

    def authorize(self, url):
        if url not in self.urls:
            raise ValueError("URL is not in the Saved allowlist")
        return URL_RE.fullmatch(url)[1]

    def request(self, method, url, code):
        if code not in self.ids or method not in ("GET", "HEAD"):
            raise ValueError("Only Saved-video reads permitted")
        u = urllib.parse.urlsplit(url)
        if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
            raise ValueError("Unsafe request address")
        host = u.hostname or ""
        if any(host.endswith("." + d) for d in ("cdninstagram.com", "fbcdn.net")):
            return
        if host not in ("www.instagram.com", "instagram.com"):
            raise ValueError("Non-media host rejected")
        if u.path.rstrip("/") == "/p/" + code and not u.query:
            return
        if u.path == "/api/v1/web/get_ruling_for_content/":
            pk = 0
            for c in code:
                pk = (
                    pk * 64
                    + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".index(
                        c
                    )
                )
            if urllib.parse.parse_qs(u.query) == {
                "content_type": ["MEDIA"],
                "target_id": [str(pk)],
            }:
                return
        raise ValueError(
            "Account, feed, DM, unrelated post, or unsupported request rejected"
        )


class QuietLogger:
    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


def video_only_product(product):
    """An Instagram carousel may mix still images and videos."""
    if isinstance(product, list):
        return [video_only_product(p) for p in product]
    if product.get("carousel_media"):
        return {
            **product,
            "carousel_media": [
                m for m in product["carousel_media"] if m.get("media_type") == 2
            ],
        }
    return product


def guard_request(policy, req, code):
    policy.request(req.get_method(), req.full_url, code)
    if req.data is not None:
        raise ValueError("Request bodies are not permitted")
    for key, _ in list(req.header_items()):
        if key.lower() in ("cookie", "authorization", "proxy-authorization"):
            req.remove_header(key)
    headers = sorted(k.lower() for k, _ in req.header_items())
    return {
        "allowed": True,
        "header_names": headers,
        "credentials": any(
            k in headers for k in ("cookie", "authorization", "proxy-authorization")
        ),
    }


def download(policy, url, directory):
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.instagram import InstagramIE
    from yt_dlp.networking._urllib import UrllibRH

    code = policy.authorize(url)
    audit = []

    class Gate(urllib.request.BaseHandler):
        handler_order = 999

        def http_request(self, req):
            u = urllib.parse.urlsplit(req.full_url)
            record = {
                "method": req.get_method(),
                "host": u.hostname,
                "path": u.path,
                "allowed": False,
            }
            audit.append(record)
            record.update(guard_request(policy, req, code))
            return req

        https_request = http_request

    class GuardedRH(UrllibRH):
        def _create_instance(self, *a, **kw):
            opener = super()._create_instance(*a, **kw)
            opener.add_handler(Gate())
            return opener

    class SavedInstagramIE(InstagramIE):
        def _real_initialize(self):
            pass  # no homepage or account session setup

        def _extract_product(self, product, *args, **kwargs):
            return super()._extract_product(
                video_only_product(product), *args, **kwargs
            )

    class SavedYDL(YoutubeDL):
        @functools.cached_property
        def _request_director(self):
            return self.build_request_director([GuardedRH], [])

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    import shutil

    if shutil.disk_usage(directory).free < 2 * 1024**3:
        raise ValueError("Insufficient free disk space for safe media processing")
    options = {
        "outtmpl": str(directory / "media-%(id)s.%(ext)s"),
        "logger": QuietLogger(),
        "quiet": True,
        "noprogress": True,
        "cachedir": False,
        "cookiefile": None,
        "cookiesfrombrowser": None,
        "username": None,
        "password": None,
        "usenetrc": False,
        "proxy": "",
        "socket_timeout": 20,
        "retries": 1,
        "extractor_retries": 0,
        "fragment_retries": 1,
        "skip_unavailable_fragments": False,
        "getcomments": False,
        "writeinfojson": False,
        "writethumbnail": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "max_filesize": 512 * 1024 * 1024,
        "format": "best[ext=mp4]/best",
        "ffmpeg_location": FFMPEG,
        "overwrites": False,
    }
    try:
        with SavedYDL(options, auto_init=False) as ydl:
            ydl.add_info_extractor(SavedInstagramIE())
            ydl.extract_info(url, download=True)
        files = sorted(directory.glob("media-*.mp4"))
        if not files:
            raise RuntimeError("No MP4 produced")
        return files
    finally:
        write_json(
            directory / "network-audit.json",
            {"source": url, "allowlist_sha256": policy.digest, "requests": audit},
        )


class Pipeline:
    def __init__(self, policy, root=DEFAULT_DATA):
        os.umask(0o077)
        self.policy = policy
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self._model = None

    def path(self, code):
        if code not in self.policy.ids:
            raise ValueError("Video is not in Saved allowlist")
        p = self.root / code
        if p.is_symlink():
            raise ValueError("Symlinked video directory rejected")
        return p

    def reusable(self, v, model):
        if (
            v.get("status") != "complete"
            or v.get("transcription_model") != model
            or not v.get("assets")
        ):
            return False
        p = self.path(v["id"])
        required = [p / "transcript.json"]
        for a in v["assets"]:
            required.extend([p / a["media"], p / a["transcript"]])
            required.extend(p / f["file"] for f in a["frames"])
            required.extend(p / s for s in a["contact_sheets"])
        return all(f.is_file() and f.stat().st_size > 0 for f in required)

    def list_videos(self):
        items = []
        for url in self.policy.urls:
            code = self.policy.authorize(url)
            p = self.path(code) / "manifest.json"
            items.append(
                json.loads(p.read_text())
                if p.exists()
                else {"id": code, "url": url, "status": "pending"}
            )
        return items

    def search(self, query, limit=20):
        terms = re.findall(r"\w+", query.casefold())
        matches = []
        if not terms:
            return matches
        for v in self.list_videos():
            t = self.path(v["id"]) / "transcript.json"
            for s in json.loads(t.read_text())["segments"] if t.exists() else []:
                score = sum(term in s["text"].casefold() for term in terms)
                if score:
                    matches.append(
                        {
                            **s,
                            "id": v["id"],
                            "url": v["url"],
                            "score": score,
                            "modality": "speech",
                        }
                    )
            t = self.path(v["id"]) / "ocr.json"
            last_text = {}
            for f in json.loads(t.read_text())["frames"] if t.exists() else []:
                score = sum(term in f["text"].casefold() for term in terms)
                if score and last_text.get(f.get("asset", 0)) != f["text"]:
                    matches.append(
                        {
                            "id": v["id"],
                            "url": v["url"],
                            "score": score,
                            "modality": "screen_text",
                            "asset": f.get("asset", 0),
                            "start": f["time"],
                            "end": f["time"],
                            "text": f["text"],
                        }
                    )
                last_text[f.get("asset", 0)] = f["text"]
        return sorted(matches, key=lambda s: (-s["score"], s["id"], s["start"]))[
            : max(1, min(limit, 100))
        ]

    def ocr(self, code):
        directory = self.path(code)
        v = json.loads((directory / "manifest.json").read_text())
        if v["status"] != "complete":
            raise ValueError("Process the video before OCR")
        output = directory / "ocr.json"
        if output.exists():
            return json.loads(output.read_text())
        frames = []
        for asset, a in enumerate(v["assets"]):
            for f in a["frames"]:
                lines = read_screen_text(directory / f["file"])
                frames.append(
                    {
                        "asset": asset,
                        "time": f["time"],
                        "file": f["file"],
                        "text": " ".join(r["text"] for r in lines),
                        "lines": lines,
                    }
                )
        data = {"engine": "rapidocr-onnxruntime", "frames": frames}
        write_json(output, data)
        return data

    def inspect(self, code, start, end, asset=0):
        p = self.path(code)
        v = json.loads((p / "manifest.json").read_text())
        assets = v.get("assets", [v])
        if asset < 0 or asset >= len(assets):
            raise ValueError("Invalid asset")
        a = assets[asset]
        if (
            not all(math.isfinite(x) for x in (start, end))
            or start < 0
            or end <= start
            or end > a["duration"] + 0.5
        ):
            raise ValueError("Time range must lie inside video")
        t = p / "transcript.json"
        segments = json.loads(t.read_text())["segments"] if t.exists() else []
        ocr_path = p / "ocr.json"
        ocr = json.loads(ocr_path.read_text())["frames"] if ocr_path.exists() else []
        return {
            "id": code,
            "url": v["url"],
            "asset": asset,
            "start": start,
            "end": end,
            "segments": [
                s
                for s in segments
                if s.get("asset", 0) == asset and s["end"] > start and s["start"] < end
            ],
            "screen_text": [
                f for f in ocr if f["asset"] == asset and start <= f["time"] <= end
            ],
            "frames": [
                {**f, "path": str(p / f["file"])}
                for f in a.get("frames", [])
                if start <= f["time"] <= end
            ],
        }

    def frame_at(self, code, timestamp, asset=0):
        import av

        p = self.path(code)
        v = json.loads((p / "manifest.json").read_text())
        assets = v.get("assets", [v])
        if asset < 0 or asset >= len(assets):
            raise ValueError("Invalid asset")
        a = assets[asset]
        if not math.isfinite(timestamp) or timestamp < 0 or timestamp >= a["duration"]:
            raise ValueError("Timestamp outside video")
        file = p / "moments" / f"{asset}-{timestamp:.3f}.jpg"
        file.parent.mkdir(exist_ok=True, mode=0o700)
        selected = None
        with av.open(str(p / a["media"])) as c:
            stream = c.streams.video[0]
            c.seek(int(timestamp / stream.time_base), stream=stream, backward=True)
            for frame in c.decode(stream):
                when = float(frame.time or 0)
                selected = (frame, when)
                if when + 0.001 >= timestamp:
                    break
        if selected is None:
            raise ValueError("No frame at timestamp")
        frame, when = selected
        image = frame.to_image()
        image.thumbnail((1280, 1280))
        image.save(file, quality=90)
        return {"path": str(file), "time": when, "url": v["url"], "asset": asset}

    def transcribe(self, media, output, model_name):
        import av

        with av.open(str(media)) as c:
            has_audio = bool(c.streams.audio)
        data = {"model": model_name, "segments": [], "has_audio": has_audio}
        if has_audio:
            from faster_whisper import WhisperModel

            if self._model is None:
                self._model = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=4,
                    download_root=str(self.root.parent / "models"),
                )
            segments, info = self._model.transcribe(
                str(media),
                beam_size=5,
                vad_filter=True,
                word_timestamps=True,
                condition_on_previous_text=False,
            )
            data.update(
                language=info.language,
                language_probability=info.language_probability,
                duration=info.duration,
            )
            for s in segments:
                data["segments"].append(
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text.strip(),
                        "words": [
                            {
                                "start": w.start,
                                "end": w.end,
                                "text": w.word,
                                "probability": w.probability,
                            }
                            for w in (s.words or [])
                        ],
                    }
                )
        write_json(output, data)

        def stamp(t):
            ms = round(t * 1000)
            h, ms = divmod(ms, 3600000)
            m, ms = divmod(ms, 60000)
            s, ms = divmod(ms, 1000)
            return f"{h:02}:{m:02}:{s:02},{ms:03}"

        output.with_suffix(".srt").write_text(
            "\n\n".join(
                f"{i}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}"
                for i, s in enumerate(data["segments"], 1)
            )
            + "\n"
        )
        return data

    def process(self, url, model="small"):
        import av, numpy as np
        from PIL import Image, ImageDraw

        code = self.policy.authorize(url)
        p = self.path(code)
        p.mkdir(exist_ok=True, mode=0o700)
        manifest = p / "manifest.json"
        old = json.loads(manifest.read_text()) if manifest.exists() else {}
        if self.reusable(old, model):
            return old
        v = {
            "id": code,
            "url": url,
            "status": "processing",
            "allowlist_sha256": self.policy.digest,
        }
        write_json(manifest, v)
        try:
            files = download(self.policy, url, p)
            assets = []
            combined = []
            for index, media in enumerate(files):
                asset_dir = p / f"asset-{index}"
                asset_dir.mkdir(exist_ok=True, mode=0o700)
                frames_dir = asset_dir / "frames"
                frames_dir.mkdir(exist_ok=True, mode=0o700)
                frames = []
                previous = None
                last_sample = -10.0
                last_regular = -10.0
                with av.open(str(media)) as c:
                    stream = c.streams.video[0]
                    duration = (
                        float(stream.duration * stream.time_base)
                        if stream.duration
                        else float(c.duration / av.time_base)
                    )
                    interval = 2.0 if duration <= 300 else 5.0
                    for frame in c.decode(stream):
                        ts = float(frame.time or 0)
                        if ts - last_sample < 0.49:
                            continue
                        last_sample = ts
                        image = frame.to_image()
                        gray = np.asarray(
                            image.resize((64, 64)).convert("L"), dtype=np.float32
                        )
                        changed = (
                            previous is not None
                            and float(np.abs(gray - previous).mean()) > 25
                        )
                        regular = ts - last_regular >= interval
                        if regular or changed:
                            file = frames_dir / f"{len(frames):05d}-{ts:.3f}.jpg"
                            image.thumbnail((960, 960))
                            image.save(file, quality=85)
                            frames.append(
                                {
                                    "time": round(ts, 3),
                                    "file": str(file.relative_to(p)),
                                    "reason": "interval" if regular else "scene",
                                }
                            )
                            if regular:
                                last_regular = ts
                        previous = gray
                transcript = asset_dir / "transcript.json"
                data = json.loads(transcript.read_text()) if transcript.exists() else {}
                if data.get("model") != model:
                    data = self.transcribe(media, transcript, model)
                combined.extend({**s, "asset": index} for s in data["segments"])
                sheets = []
                for offset in range(0, len(frames), 24):
                    batch = frames[offset : offset + 24]
                    sheet = Image.new(
                        "RGB", (960, math.ceil(len(batch) / 4) * 270), "#171717"
                    )
                    draw = ImageDraw.Draw(sheet)
                    for i, f in enumerate(batch):
                        with Image.open(p / f["file"]) as im:
                            im.thumbnail((232, 240))
                            x = (i % 4) * 240
                            y = (i // 4) * 270
                            sheet.paste(im, (x + (240 - im.width) // 2, y))
                            draw.text(
                                (x + 5, y + 245), f"{f['time']:.3f}s", fill="white"
                            )
                    name = asset_dir / f"contact-{offset // 24 + 1:03}.jpg"
                    sheet.save(name, quality=85)
                    sheets.append(str(name.relative_to(p)))
                assets.append(
                    {
                        "media": media.name,
                        "duration": duration,
                        "frames": frames,
                        "contact_sheets": sheets,
                        "transcript": str(transcript.relative_to(p)),
                        "sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
                    }
                )
            write_json(p / "transcript.json", {"model": model, "segments": combined})
            v.update(
                assets=assets,
                duration=assets[0]["duration"],
                status="complete",
                transcription_model=model,
                note="Sampled visual evidence and ASR; no semantic summary asserted.",
            )
        except Exception as e:
            v.update(status="failed", error_type=type(e).__name__)
            (p / "error.txt").write_text(str(e))
            os.chmod(p / "error.txt", 0o600)
        write_json(manifest, v)
        return v


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--model", default="small")
    run.add_argument("--limit", type=int)
    sub.add_parser("ocr")
    sub.add_parser("list")
    search = sub.add_parser("search")
    search.add_argument("query")
    ins = sub.add_parser("inspect")
    ins.add_argument("id")
    ins.add_argument("start", type=float)
    ins.add_argument("end", type=float)
    ins.add_argument("--asset", type=int, default=0)
    fr = sub.add_parser("frame")
    fr.add_argument("id")
    fr.add_argument("timestamp", type=float)
    fr.add_argument("--asset", type=int, default=0)
    args = parser.parse_args()
    p = Pipeline(SavedPolicy(args.allowlist), args.data)
    from .archive import Archive, DEFAULT_ARCHIVE

    use_archive = args.data == DEFAULT_DATA and args.allowlist == DEFAULT_ALLOWLIST
    archived = (
        Archive(p.policy)
        if (use_archive and (DEFAULT_ARCHIVE / "index.ref").exists())
        else None
    )
    if args.command == "run":
        results = []
        # Archived Saved assets need no network reads or repeated OCR/ASR.
        for i, url in enumerate(p.policy.urls[: args.limit]):
            code = p.policy.authorize(url)
            if archived and code in archived.entries:
                results.append(archived.entry(code)["manifest"])
                print(
                    json.dumps(
                        {"index": i + 1, "status": "complete", "encrypted_cache": True}
                    ),
                    flush=True,
                )
                continue
            r = p.process(url, args.model)
            results.append(r)
            if r["status"] == "complete":
                try:
                    p.ocr(r["id"])
                except Exception as e:
                    r.update(
                        status="failed", error_type=type(e).__name__, failed_stage="ocr"
                    )
                    write_json(p.path(r["id"]) / "manifest.json", r)
            print(
                json.dumps(
                    {
                        "index": i + 1,
                        "status": r["status"],
                        "error_type": r.get("error_type"),
                    }
                ),
                flush=True,
            )
            time.sleep(2)
        write_json(
            p.root / "run-report.json",
            {
                "allowlist_sha256": p.policy.digest,
                "total": len(results),
                "complete": sum(x["status"] == "complete" for x in results),
                "failed": sum(x["status"] == "failed" for x in results),
            },
        )
        if use_archive and args.limit is None:
            from .archive import build_archive, key_bytes, prune_plaintext

            storage = build_archive(
                p, DEFAULT_ARCHIVE, key_bytes(), allow_incomplete=True
            )
            write_json(p.root / "storage-verification.json", storage)
            write_json(
                p.root / "prune-verification.json",
                prune_plaintext(p, Archive(p.policy)),
            )
        if any(x["status"] == "failed" for x in results):
            raise SystemExit(1)
    elif args.command == "ocr":
        if archived:
            print(
                json.dumps(
                    {
                        "archived_videos": len(archived.list_videos()),
                        "ocr": "already archived",
                    }
                )
            )
            return
        for i, v in enumerate(p.list_videos()):
            if v["status"] == "complete":
                data = p.ocr(v["id"])
                print(
                    json.dumps({"index": i + 1, "ocr_frames": len(data["frames"])}),
                    flush=True,
                )
    elif args.command == "list":
        print(json.dumps((archived or p).list_videos(), indent=2))
    elif args.command == "search":
        print(json.dumps((archived or p).search(args.query), indent=2))
    elif args.command == "inspect":
        if archived:
            with archived.materialize(args.id) as local:
                evidence = local.inspect(args.id, args.start, args.end, args.asset)
                evidence["frames"] = [
                    {k: v for k, v in f.items() if k not in ("file", "path")}
                    for f in evidence["frames"]
                ]
            print(json.dumps(evidence, indent=2))
            return
        print(
            json.dumps(p.inspect(args.id, args.start, args.end, args.asset), indent=2)
        )
    elif args.command == "frame":
        if archived:
            with archived.materialize(args.id) as local:
                frame = local.frame_at(args.id, args.timestamp, args.asset)
                preview = (
                    Path("/run/user") / str(os.getuid()) / "saved-video-preview.jpg"
                )
                if preview.is_symlink():
                    raise ValueError("Unsafe preview path")
                preview.write_bytes(Path(frame["path"]).read_bytes())
                preview.chmod(0o600)
                frame["path"] = str(preview)
            print(json.dumps(frame, indent=2))
            return
        print(json.dumps(p.frame_at(args.id, args.timestamp, args.asset), indent=2))


if __name__ == "__main__":
    main()
