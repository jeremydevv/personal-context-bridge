"""Integration checks for dependency compatibility and real timestamp seeking."""

import json, subprocess, wave
from personal_context.saved_video.pipeline import Pipeline, SavedPolicy


def test_local_audio_decoder_accepts_installed_pyav(tmp_path):
    from faster_whisper.audio import decode_audio

    p = tmp_path / "silence.wav"
    with wave.open(str(p), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\0\0" * 16000)
    audio = decode_audio(str(p))
    assert len(audio) == 16000


def test_frame_seek_returns_real_timestamp_and_image(tmp_path):
    from PIL import Image

    allow = tmp_path / "urls.txt"
    allow.write_text("https://www.instagram.com/p/Fictional_123/\n")
    p = Pipeline(SavedPolicy(allow), tmp_path / "data")
    d = p.path("Fictional_123")
    d.mkdir()
    ff = __import__("os").environ.get("SAVED_VIDEO_FFMPEG", "ffmpeg")
    subprocess.run(
        [
            str(ff),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=160x90:rate=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(d / "video.mp4"),
        ],
        check=True,
    )
    (d / "manifest.json").write_text(
        json.dumps(
            {"url": allow.read_text().strip(), "duration": 3, "media": "video.mp4"}
        )
    )
    f = p.frame_at("Fictional_123", 1.25)
    assert 1.25 <= f["time"] <= 1.4
    with Image.open(f["path"]) as im:
        assert im.size == (160, 90)


def test_ocr_reads_rendered_text_without_network(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    from personal_context.saved_video.pipeline import read_screen_text

    im = Image.new("RGB", (800, 160), "white")
    draw = ImageDraw.Draw(im)
    draw.text(
        (20, 35),
        "BLUE BICYCLE",
        font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 60),
        fill="black",
    )
    f = tmp_path / "text.png"
    im.save(f)
    rows = read_screen_text(f)
    assert "BLUE BICYCLE" in " ".join(r["text"] for r in rows).upper()
    assert all(0 <= r["confidence"] <= 1 for r in rows)


def test_last_moment_returns_last_displayed_frame(tmp_path):
    allow = tmp_path / "urls.txt"
    allow.write_text("https://www.instagram.com/p/Fictional_123/\n")
    p = Pipeline(SavedPolicy(allow), tmp_path / "data")
    d = p.path("Fictional_123")
    d.mkdir()
    ff = __import__("os").environ.get("SAVED_VIDEO_FFMPEG", "ffmpeg")
    subprocess.run(
        [
            str(ff),
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:d=2:r=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(d / "media.mp4"),
        ],
        check=True,
    )
    (d / "manifest.json").write_text(
        json.dumps(
            {"url": allow.read_text().strip(), "duration": 2, "media": "media.mp4"}
        )
    )
    frame = p.frame_at("Fictional_123", 1.99)
    assert frame["time"] == 1.9


def test_long_silent_video_builds_spaced_frames_and_reuses_evidence(
    tmp_path, monkeypatch
):
    from personal_context.saved_video import pipeline

    allow = tmp_path / "urls.txt"
    allow.write_text("https://www.instagram.com/p/Fictional_123/\n")
    p = Pipeline(SavedPolicy(allow), tmp_path / "data")
    d = p.path("Fictional_123")
    d.mkdir()
    ff = __import__("os").environ.get("SAVED_VIDEO_FFMPEG", "ffmpeg")
    subprocess.run(
        [
            str(ff),
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:d=360:r=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(d / "media-test.mp4"),
        ],
        check=True,
    )
    # The external download is the only substituted boundary. Decode, frame extraction,
    # no-audio handling, manifests, timestamps and cache checks all run for real.
    monkeypatch.setattr(pipeline, "download", lambda *args: [d / "media-test.mp4"])
    v = p.process(allow.read_text().strip())
    assert v["status"] == "complete"
    assert v["assets"][0]["duration"] == 360
    assert len(v["assets"][0]["frames"]) == 72
    assert [f["time"] for f in v["assets"][0]["frames"][:3]] == [0, 5, 10]
    assert json.loads((d / "transcript.json").read_text())["segments"] == []

    def reject_network(*args):
        raise AssertionError("Cache replay must not download")

    monkeypatch.setattr(pipeline, "download", reject_network)
    assert p.process(allow.read_text().strip())["status"] == "complete"
