"""Exercise the actual stdio protocol with fictional local media, no network."""

import json
import os
import subprocess
import anyio
from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_delivers_images_evidence_and_rejects_unlisted_video(tmp_path):
    urls = tmp_path / "urls.txt"
    urls.write_text("https://www.instagram.com/p/Fictional_123/\n")
    data = tmp_path / "data"
    video = data / "Fictional_123"
    video.mkdir(parents=True)
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
            str(video / "media.mp4"),
        ],
        check=True,
    )
    Image.new("RGB", (160, 90), "blue").save(video / "sheet.jpg")
    manifest = {
        "id": "Fictional_123",
        "url": urls.read_text().strip(),
        "status": "complete",
        "assets": [
            {
                "media": "media.mp4",
                "duration": 2,
                "frames": [{"time": 0, "file": "sheet.jpg"}],
                "contact_sheets": ["sheet.jpg"],
            }
        ],
    }
    (video / "manifest.json").write_text(json.dumps(manifest))
    (video / "transcript.json").write_text(
        json.dumps(
            {"segments": [{"start": 0, "end": 1, "text": "A fictional blue bicycle."}]}
        )
    )

    async def check():
        params = StdioServerParameters(
            command=__import__("sys").executable,
            args=["-m", "personal_context.saved_video.mcp_server"],
            env={
                **os.environ,
                "HOME": str(tmp_path),
                "PERSONAL_CONTEXT_REFRESH_ENABLED": "0",
                "PERSONAL_CONTEXT_KEY_FILE": str(tmp_path / "missing-fixture.key"),
                "PERSONAL_CONTEXT_REFRESH_DIR": str(tmp_path / "refresh"),
                "SAVED_VIDEO_ALLOWLIST": str(urls),
                "SAVED_VIDEO_DATA": str(data),
            },
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {
                    "list_saved_videos", "search_saved_videos", "get_video_evidence",
                    "get_video_frame", "get_video_storyboard",
                    "data_source_status", "data_refresh_status",
                }
                assert all(tool.annotations.readOnlyHint for tool in tools.tools)
                status = await session.call_tool("data_source_status", {})
                assert not status.isError
                payload = status.structuredContent or json.loads(status.content[0].text)
                assert set(payload["sources"]) == {"saved_video"}
                denied = await session.call_tool("data_source_status", {"source": "mail"})
                assert denied.isError
                result = await session.call_tool(
                    "search_saved_videos", {"query": "bicycle"}
                )
                assert not result.isError
                assert "bicycle" in result.content[0].text
                result = await session.call_tool(
                    "get_video_evidence",
                    {"video_id": "Fictional_123", "start": 0, "end": 1},
                )
                assert not result.isError
                result = await session.call_tool(
                    "get_video_frame", {"video_id": "Fictional_123", "timestamp": 0.5}
                )
                assert not result.isError and any(
                    c.type == "image" for c in result.content
                )
                result = await session.call_tool(
                    "get_video_storyboard", {"video_id": "Fictional_123"}
                )
                assert not result.isError and result.content[0].type == "image"
                result = await session.call_tool(
                    "get_video_frame", {"video_id": "NOT_SAVED", "timestamp": 0.5}
                )
                assert result.isError
                urls.write_text("")
                result = await session.call_tool(
                    "get_video_frame", {"video_id": "Fictional_123", "timestamp": 0.5}
                )
                assert result.isError
                urls.write_text("https://www.instagram.com/p/Fictional_123/\n")

    anyio.run(check)

    # Exercise the full opt-in Bridge -> isolated encrypted evidence worker.
    from personal_context.saved_video.archive import build_archive
    from personal_context.saved_video.pipeline import Pipeline, SavedPolicy
    from personal_context.store import Store

    key = tmp_path / "archive.key"
    key.write_bytes(b"x" * 32)
    key.chmod(0o600)
    archive = tmp_path / "encrypted"
    (video / "ocr.json").write_text(
        json.dumps({"frames": [{"asset": 0, "time": 0, "text": "fictional bicycle"}]})
    )
    build_archive(Pipeline(SavedPolicy(urls), data), archive, key.read_bytes())
    database = tmp_path / "context.sqlite3"
    Store(database, key_file=key).close()

    async def bridge_check():
        params = StdioServerParameters(
            command=__import__("sys").executable,
            args=["-m", "personal_context.mcp_server"],
            env={
                **os.environ,
                "PERSONAL_CONTEXT_SAVED_VIDEO_ENABLED": "1",
                "PERSONAL_CONTEXT_DB": str(database),
                "PERSONAL_CONTEXT_KEY_FILE": str(key),
                "HOME": str(tmp_path),
                "PERSONAL_CONTEXT_REFRESH_ENABLED": "0",
                "PERSONAL_CONTEXT_KEY_FILE": str(tmp_path / "missing-fixture.key"),
                "PERSONAL_CONTEXT_REFRESH_DIR": str(tmp_path / "refresh"),
                "SAVED_VIDEO_ALLOWLIST": str(urls),
                "SAVED_VIDEO_DATA": str(data),
                "SAVED_VIDEO_ARCHIVE": str(archive),
            },
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert all(
                    t.annotations.readOnlyHint
                    for t in tools
                    if t.name.startswith(("get_video_", "search_saved_", "list_saved_"))
                )
                result = await session.call_tool(
                    "search_personal_context",
                    {"kind": "instagram_saved_video", "query": "bicycle"},
                )
                assert not result.isError and "fictional" in str(result.content)
                result = await session.call_tool(
                    "get_video_frame", {"video_id": "Fictional_123", "timestamp": 0.5}
                )
                assert not result.isError and any(
                    c.type == "image" for c in result.content
                )
                result = await session.call_tool(
                    "get_video_frame", {"video_id": "NOT_SAVED", "timestamp": 0.5}
                )
                assert result.isError

    anyio.run(bridge_check)
