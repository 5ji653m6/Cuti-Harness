import os
import shutil
import subprocess
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ffmpeg_service import (
    _input_seek_sec,
    concat_videos,
    extract_frame,
    get_audio_duration,
    get_video_info,
)


def test_input_seek_sec_floors_to_milliseconds():
    assert _input_seek_sec(15.041667) == 15.041
    assert _input_seek_sec(9.916667) == 9.916
    assert _input_seek_sec(-1.0) == 0.0


def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_clip(path: str, *, color: str, video_seconds: float = 1.0, audio_seconds: float = 1.08) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color={color}:size=320x240:rate=24:duration={video_seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={audio_seconds}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", path,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


def _make_silent_clip(path: str, *, color: str, video_seconds: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color={color}:size=320x240:rate=24:duration={video_seconds}",
            "-map", "0:v:0", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg/ffprobe not in PATH")
async def test_concat_does_not_duplicate_video_tail_for_longer_audio():
    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "first.mp4")
        second = os.path.join(tmp, "second.mp4")
        output = os.path.join(tmp, "output.mp4")
        _make_clip(first, color="red")
        _make_clip(second, color="blue")

        first_info = await get_video_info(first)
        second_info = await get_video_info(second)
        await concat_videos([first, second], output, normalize=True)
        output_info = await get_video_info(output)

        assert output_info["nb_frames"] == first_info["nb_frames"] + second_info["nb_frames"]


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg/ffprobe not in PATH")
async def test_extract_last_frame_uses_final_decoded_video_frame():
    with tempfile.TemporaryDirectory() as tmp:
        source = os.path.join(tmp, "source.mp4")
        frame = os.path.join(tmp, "last.png")
        _make_clip(source, color="green")

        info = await get_video_info(source)
        result = await extract_frame(source, frame, None, position="last", image_format="png")

        expected_pts = _input_seek_sec((info["nb_frames"] - 1) / info["fps"])
        assert result["position"] == "last"
        assert abs(result["timestamp"] - expected_pts) < 1e-9
        assert os.path.getsize(frame) > 0


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg/ffprobe not in PATH")
async def test_concat_supports_short_continuation_crossfade():
    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "first.mp4")
        second = os.path.join(tmp, "second.mp4")
        output = os.path.join(tmp, "output.mp4")
        _make_clip(first, color="red")
        _make_clip(second, color="blue")

        await concat_videos(
            [first, second],
            output,
            normalize=True,
            transition_duration=0.125,
        )
        output_info = await get_video_info(output)

        assert 44 <= output_info["nb_frames"] <= 46
        assert abs(output_info["video_duration"] - 1.875) < 0.1


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg/ffprobe not in PATH")
async def test_concat_preserves_native_audio_and_fills_silence_for_missing_track():
    with tempfile.TemporaryDirectory() as tmp:
        with_audio = os.path.join(tmp, "with_audio.mp4")
        silent = os.path.join(tmp, "silent.mp4")
        output = os.path.join(tmp, "output.mp4")
        _make_clip(with_audio, color="red", audio_seconds=1.0)
        _make_silent_clip(silent, color="blue")

        await concat_videos([with_audio, silent], output, normalize=True)
        output_info = await get_video_info(output)

        assert output_info["has_audio"] is True
        assert output_info["audio_codec"] == "aac"
        assert abs(output_info["video_duration"] - 2.0) < 0.1
        audio_duration = await get_audio_duration(output)
        assert abs(audio_duration - output_info["video_duration"]) < 0.1


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg/ffprobe not in PATH")
async def test_concat_adds_silent_aac_when_every_input_is_silent():
    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "first.mp4")
        second = os.path.join(tmp, "second.mp4")
        output = os.path.join(tmp, "output.mp4")
        _make_silent_clip(first, color="red")
        _make_silent_clip(second, color="blue")

        await concat_videos([first, second], output, normalize=True)
        output_info = await get_video_info(output)

        assert output_info["has_audio"] is True
        assert output_info["audio_codec"] == "aac"
        audio_duration = await get_audio_duration(output)
        assert abs(audio_duration - output_info["video_duration"]) < 0.1


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg/ffprobe not in PATH")
async def test_concat_adds_silent_aac_to_a_single_silent_input():
    with tempfile.TemporaryDirectory() as tmp:
        source = os.path.join(tmp, "source.mp4")
        output = os.path.join(tmp, "output.mp4")
        _make_silent_clip(source, color="green")

        await concat_videos([source], output, normalize=True)
        output_info = await get_video_info(output)

        assert output_info["has_audio"] is True
        assert output_info["audio_codec"] == "aac"
        audio_duration = await get_audio_duration(output)
        assert abs(audio_duration - output_info["video_duration"]) < 0.1


@pytest.mark.asyncio
async def test_concat_mixed_audio_builds_silent_track_for_missing_input():
    with_audio = {
        "duration": 1.0,
        "video_duration": 1.0,
        "width": 320,
        "height": 240,
        "fps": 24.0,
        "codec": "h264",
        "pix_fmt": "yuv420p",
        "has_audio": True,
        "time_base": "1/12288",
        "audio_codec": "aac",
        "audio_sample_rate": 44100,
        "audio_channels": 2,
        "audio_channel_layout": "stereo",
        "audio_time_base": "1/44100",
    }
    silent = {**with_audio, "has_audio": False}
    with tempfile.TemporaryDirectory() as tmp:
        output = os.path.join(tmp, "output.mp4")
        run = AsyncMock(return_value=(0, "", ""))
        inspect = AsyncMock(side_effect=[with_audio, silent])
        with (
            patch("app.services.ffmpeg_service.run_ffmpeg", run),
            patch("app.services.ffmpeg_service.get_video_info", inspect),
        ):
            await concat_videos(
                [os.path.join(tmp, "one.mp4"), os.path.join(tmp, "two.mp4")],
                output,
                normalize=True,
            )

        command = run.await_args.args[0]
        filt = command[command.index("-filter_complex") + 1]
        assert "[0:a]aformat=" in filt
        assert "anullsrc=sample_rate=44100:channel_layout=stereo" in filt
        assert "concat=n=2:v=1:a=1[outv][outa]" in filt
        assert command[command.index("-c:a") + 1] == "aac"


@pytest.mark.asyncio
async def test_concat_normalize_uses_copy_for_identical_hevc_main10_streams():
    """Seedance segments must not spend 20 minutes transcoding compatible HEVC."""
    info = {
        "duration": 15.072,
        "video_duration": 15.0,
        "width": 1920,
        "height": 1080,
        "fps": 24.0,
        "nb_frames": 360,
        "codec": "hevc",
        "pix_fmt": "yuv420p10le",
        "has_audio": True,
        "time_base": "1/12288",
        "audio_codec": "aac",
        "audio_sample_rate": 32000,
        "audio_channels": 2,
        "audio_channel_layout": "stereo",
        "audio_time_base": "1/32000",
    }
    with tempfile.TemporaryDirectory() as tmp:
        output = os.path.join(tmp, "output.mp4")
        run = AsyncMock(return_value=(0, "", ""))
        inspect = AsyncMock(return_value=info)
        with (
            patch("app.services.ffmpeg_service.run_ffmpeg", run),
            patch("app.services.ffmpeg_service.get_video_info", inspect),
        ):
            await concat_videos(
                [os.path.join(tmp, "one.mp4"), os.path.join(tmp, "two.mp4")],
                output,
                normalize=True,
            )

        command = run.await_args.args[0]
        assert command[command.index("-c") + 1] == "copy"
        assert "libx264" not in command


@pytest.mark.asyncio
async def test_concat_xfade_puts_fps_after_settb():
    """FFmpeg 7.1 xfade rejects streams that rewrite timebase after fps."""
    info = {
        "duration": 15.08,
        "video_duration": 15.08,
        "width": 1920,
        "height": 1080,
        "fps": 24.0,
        "nb_frames": 362,
        "codec": "h264",
        "pix_fmt": "yuv420p",
        "has_audio": True,
        "time_base": "1/12288",
        "audio_codec": "aac",
        "audio_sample_rate": 44100,
        "audio_channels": 2,
        "audio_channel_layout": "stereo",
        "audio_time_base": "1/44100",
    }
    with tempfile.TemporaryDirectory() as tmp:
        output = os.path.join(tmp, "output.mp4")
        run = AsyncMock(return_value=(0, "", ""))
        inspect = AsyncMock(return_value=info)
        with (
            patch("app.services.ffmpeg_service.run_ffmpeg", run),
            patch("app.services.ffmpeg_service.get_video_info", inspect),
        ):
            await concat_videos(
                [os.path.join(tmp, "one.mp4"), os.path.join(tmp, "two.mp4")],
                output,
                normalize=True,
                transition_duration=0.125,
            )

        command = run.await_args.args[0]
        filt = command[command.index("-filter_complex") + 1]
        assert "settb=AVTB,setpts=PTS-STARTPTS,fps=24.000000" in filt
        assert "fps=24.000000,settb=AVTB" not in filt


@pytest.mark.asyncio
async def test_concat_timestamp_corruption_forces_transcode_without_reentering_copy():
    source_info = {
        "duration": 10.0,
        "video_duration": 10.0,
        "width": 1920,
        "height": 1080,
        "fps": 24.0,
        "nb_frames": 240,
        "codec": "hevc",
        "pix_fmt": "yuv420p10le",
        "has_audio": True,
        "time_base": "1/12288",
        "audio_codec": "aac",
        "audio_sample_rate": 32000,
        "audio_channels": 2,
        "audio_channel_layout": "stereo",
        "audio_time_base": "1/32000",
    }
    corrupt_output_info = {**source_info, "duration": 30.0, "video_duration": 30.0}
    with tempfile.TemporaryDirectory() as tmp:
        output = os.path.join(tmp, "output.mp4")
        run = AsyncMock(return_value=(0, "", ""))
        inspect = AsyncMock(side_effect=[
            source_info,
            source_info,
            corrupt_output_info,
            source_info,
            source_info,
        ])
        with (
            patch("app.services.ffmpeg_service.run_ffmpeg", run),
            patch("app.services.ffmpeg_service.get_video_info", inspect),
            patch("app.services.ffmpeg_service.os.unlink"),
        ):
            await concat_videos(
                [os.path.join(tmp, "one.mp4"), os.path.join(tmp, "two.mp4")],
                output,
                normalize=True,
            )

        assert run.await_count == 2
        copy_command = run.await_args_list[0].args[0]
        transcode_command = run.await_args_list[1].args[0]
        assert copy_command[copy_command.index("-c") + 1] == "copy"
        assert "libx264" in transcode_command
