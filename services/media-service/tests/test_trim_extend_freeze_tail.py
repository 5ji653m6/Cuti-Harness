"""freeze_or_tail_slow：小缺口静帧 concat copy；大缺口尾部放慢 / 整片放慢。"""
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
async def test_freeze_or_tail_small_gap_freeze():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        out = os.path.join(tmp, "out.mp4")
        _make_synthetic_mp4(src, seconds=5.0, fps=24)
        d0 = (await get_video_info(src))["duration"]
        target = d0 + 0.12
        await trim_video(src, out, target, mode="freeze_or_tail_slow", skip_if_within_sec=0.0)
        d1 = (await get_video_info(out))["duration"]
        assert abs(d1 - target) < 0.18, f"dur={d1} target={target}"


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not in PATH")
async def test_freeze_or_tail_large_gap_tail_slow_or_uniform():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        out = os.path.join(tmp, "out.mp4")
        _make_synthetic_mp4(src, seconds=5.0, fps=24)
        d0 = (await get_video_info(src))["duration"]
        target = d0 + 0.55
        await trim_video(src, out, target, mode="freeze_or_tail_slow", skip_if_within_sec=0.0)
        d1 = (await get_video_info(out))["duration"]
        assert abs(d1 - target) < 0.25, f"dur={d1} target={target}"


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not in PATH")
async def test_freeze_or_tail_shorten_when_longer():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        out = os.path.join(tmp, "out.mp4")
        _make_synthetic_mp4(src, seconds=8.0, fps=24)
        target = 3.2
        await trim_video(src, out, target, mode="freeze_or_tail_slow", skip_if_within_sec=0.0)
        d1 = (await get_video_info(out))["duration"]
        assert abs(d1 - target) < 0.15, f"dur={d1} target={target}"
