"""
trim_video：截短路径用 -t（墙钟）+ libx264，输出时长贴近 target（不再按 round(target*fps) 帧数量化）。

实现见 app/services/ffmpeg_service.py::trim_video（current_dur > target 分支）。
需本机 ffmpeg 可用。
"""
import os
import shutil
import subprocess
import tempfile

import pytest

from app.services.ffmpeg_service import get_video_info, trim_video


def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None


def _make_synthetic_mp4(path: str, seconds: float, fps: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=320x240:rate={fps}",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            path,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not in PATH")
async def test_trim_video_down_matches_wall_clock_target():
    """截短：-t 墙钟，输出时长贴近 target（允许编码/探针少量误差，约一帧量级）。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        out = os.path.join(tmp, "out.mp4")
        _make_synthetic_mp4(src, seconds=10.0, fps=24)

        info_in = await get_video_info(src)
        fps = info_in["fps"]
        assert abs(fps - 24) < 0.5

        target = 3.1
        await trim_video(src, out, target, mode="trim_only")

        info_out = await get_video_info(out)
        dur = info_out["duration"]
        assert abs(dur - target) < 0.12, (
            f"duration={dur} expected≈{target} (wall-clock -t trim)"
        )


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not in PATH")
async def test_trim_video_shorter_than_target_trim_only_uses_stream_copy():
    """片源短于 target 且 trim_only：走 -t + copy 分支（与截长不同）。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "short.mp4")
        out = os.path.join(tmp, "out.mp4")
        _make_synthetic_mp4(src, seconds=2.0, fps=25)

        await trim_video(src, out, 5.0, mode="trim_only")
        info_out = await get_video_info(out)
        assert info_out["duration"] <= 2.05
