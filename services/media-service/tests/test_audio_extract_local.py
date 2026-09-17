"""本地 FFmpeg：extract_audio 无音轨返回 False、有音轨返回 True（不启 HTTP）。"""
import asyncio
import os
import subprocess
import tempfile

import pytest


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=5)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.fixture
def video_no_audio(tmp_path):
    out = tmp_path / "silent.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=128x128:rate=25",
        "-t", "0.5",
        "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out)


@pytest.fixture
def video_with_audio(tmp_path):
    out = tmp_path / "with_audio.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=128x128:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.5",
        "-t", "0.5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out)


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_extract_audio_false_when_no_audio_stream(video_no_audio):
    from app.services import ffmpeg_service

    out_mp3 = str(video_no_audio).replace(".mp4", "_out.mp3")
    ok = await ffmpeg_service.extract_audio(video_no_audio, out_mp3, "mp3", "192k")
    assert ok is False
    assert not os.path.isfile(out_mp3)


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_extract_audio_true_when_has_audio(video_with_audio):
    from app.services import ffmpeg_service

    out_mp3 = str(video_with_audio).replace(".mp4", "_out.mp3")
    ok = await ffmpeg_service.extract_audio(video_with_audio, out_mp3, "mp3", "192k")
    assert ok is True
    assert os.path.isfile(out_mp3)
    assert os.path.getsize(out_mp3) > 100
