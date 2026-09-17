"""本地 FFmpeg：trim_audio_with_fade / extract_audio_peaks 直接函数级集成测试（不启 HTTP）。

跑：
  conda run -n cuti-video-local pytest tests/test_audio_trim_fade_and_peaks_local.py -v -s
"""
import asyncio
import os
import subprocess

import pytest


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=5)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.fixture
def sine_audio_5s(tmp_path):
    """生成一个 5 秒 440Hz mp3，用于测试。"""
    out = tmp_path / "sine_5s.mp3"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=5",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    assert out.exists() and out.stat().st_size > 0
    return str(out)


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_trim_audio_stays_within_requested_duration(tmp_path):
    """15s 切窗必须按采样点卡住，不能像 -c copy 那样落到 16s+。"""
    from app.services import ffmpeg_service

    src = tmp_path / "sine_20s.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=20",
            "-c:a", "libmp3lame", "-q:a", "4",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    copied = tmp_path / "copy_15s.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-ss", "0", "-t", "15",
            "-c", "copy",
            str(copied),
        ],
        check=True,
        capture_output=True,
    )
    out = str(tmp_path / "reencoded_15s.mp3")
    await ffmpeg_service.trim_audio(str(src), out, start=0.0, duration=15.0)
    decoded = await ffmpeg_service.get_audio_duration(out)
    copy_dur = await ffmpeg_service.get_audio_duration(str(copied))
    assert 14.85 <= decoded <= 15.08, (
        f"re-encode duration {decoded} 超出 14.85~15.08s (copy was {copy_dur})"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_trim_audio_rejects_non_positive_duration(sine_audio_5s, tmp_path):
    from app.services import ffmpeg_service

    with pytest.raises(ValueError):
        await ffmpeg_service.trim_audio(
            sine_audio_5s, str(tmp_path / "out.mp3"), start=0.0, duration=0.0,
        )


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_trim_audio_with_fade_basic(sine_audio_5s, tmp_path):
    """裁切 5s 中段 [1.0..3.0]，淡入 0.3s + 淡出 0.5s。"""
    from app.services import ffmpeg_service

    out = str(tmp_path / "out.mp3")
    await ffmpeg_service.trim_audio_with_fade(
        sine_audio_5s, out,
        start=1.0, duration=2.0,
        fade_in_sec=0.3, fade_out_sec=0.5,
    )
    assert os.path.isfile(out) and os.path.getsize(out) > 100
    decoded = await ffmpeg_service.get_audio_duration(out)
    # 允许 ~0.05s 编码误差
    assert 1.9 <= decoded <= 2.1, f"decoded duration {decoded} 超出 1.9~2.1s 范围"


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_trim_audio_with_fade_zero_fade(sine_audio_5s, tmp_path):
    """fade=0 时也能正常工作（等同 trim 但走 libmp3lame 重编码）。"""
    from app.services import ffmpeg_service

    out = str(tmp_path / "out.mp3")
    await ffmpeg_service.trim_audio_with_fade(
        sine_audio_5s, out,
        start=0.0, duration=1.0,
        fade_in_sec=0.0, fade_out_sec=0.0,
    )
    assert os.path.isfile(out) and os.path.getsize(out) > 100
    decoded = await ffmpeg_service.get_audio_duration(out)
    assert 0.9 <= decoded <= 1.1, f"decoded duration {decoded} 超出 0.9~1.1s 范围"


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_trim_audio_with_fade_clamps_oversized_fade(sine_audio_5s, tmp_path):
    """fade 之和大于 duration 时按比例缩放，不应抛错。"""
    from app.services import ffmpeg_service

    out = str(tmp_path / "out.mp3")
    # duration=1.0 但 fade_in=0.8 + fade_out=0.8 = 1.6 > 1.0，应 clamp 到 0.8 比例
    await ffmpeg_service.trim_audio_with_fade(
        sine_audio_5s, out,
        start=0.0, duration=1.0,
        fade_in_sec=0.8, fade_out_sec=0.8,
    )
    assert os.path.isfile(out) and os.path.getsize(out) > 100


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_extract_audio_peaks_basic(sine_audio_5s):
    """正弦波 5 秒抽 256 桶 peaks，应得到接近常数的归一化值（sine 包络稳定 → 多数桶接近 1.0）。"""
    from app.services import ffmpeg_service

    duration, peaks = await ffmpeg_service.extract_audio_peaks(sine_audio_5s, sample_count=256)
    assert 4.9 <= duration <= 5.1, f"duration {duration} 超出 4.9~5.1s"
    assert len(peaks) == 256
    # 全部归一化在 [0,1]
    assert all(0.0 <= v <= 1.0 for v in peaks)
    # 中段（去掉首尾 5%）应大部分接近 1.0（正弦稳态）
    mid = peaks[12:-12]
    high_count = sum(1 for v in mid if v >= 0.7)
    assert high_count >= len(mid) * 0.8, f"sine 中段应大量 >= 0.7，实际 {high_count}/{len(mid)}"


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_extract_audio_peaks_short_audio(tmp_path):
    """非常短（0.2s）音频也不应崩溃。"""
    from app.services import ffmpeg_service

    short = tmp_path / "short.mp3"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.2",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(short),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    duration, peaks = await ffmpeg_service.extract_audio_peaks(str(short), sample_count=64)
    assert 0.15 <= duration <= 0.3
    assert len(peaks) == 64
    assert all(0.0 <= v <= 1.0 for v in peaks)


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
async def test_trim_audio_with_fade_invalid_duration(sine_audio_5s, tmp_path):
    """duration <= 0 应抛 ValueError。"""
    from app.services import ffmpeg_service

    out = str(tmp_path / "out.mp3")
    with pytest.raises(ValueError):
        await ffmpeg_service.trim_audio_with_fade(
            sine_audio_5s, out, start=0.0, duration=0.0,
        )
