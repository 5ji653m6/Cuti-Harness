"""
强制不跳过 trim（skip_if_within_sec=0）时，get_video_info（解码时长）相对 target 的偏差。

跑法（看打印表）: pytest tests/test_trim_no_skip_probe_delta.py -s -q
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
async def test_force_trim_no_skip_shorten_probe_deltas(capsys):
    """长片截短：skip=0 强制 -t+libx264，记录 probe−target（与生产 post_gen_trim 路径一致 mode=trim_only）。"""
    rows = []
    for fps in (24, 30):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.mp4")
            _make_synthetic_mp4(src, seconds=15.0, fps=fps)
            in_dur = (await get_video_info(src))["duration"]
            for target in (2.1, 2.6, 2.8, 4.1, 5.6):
                if target >= in_dur - 0.05:
                    continue
                out = os.path.join(tmp, f"out_{fps}_{target}.mp4")
                await trim_video(
                    src, out, target, mode="trim_only", skip_if_within_sec=0.0
                )
                dur = (await get_video_info(out))["duration"]
                delta = dur - target
                rows.append((fps, target, dur, delta))
                assert abs(delta) < 0.12, (
                    f"fps={fps} target={target} probe={dur:.4f} Δ={delta:+.4f}"
                )

    with capsys.disabled():
        print("\n--- force trim (skip_if_within_sec=0), trim_only shorten ---")
        print(f"{'fps':>4} {'target':>8} {'probe':>10} {'Δ(probe-target)':>18}")
        for fps, target, dur, delta in rows:
            print(f"{fps:4d} {target:8.2f} {dur:10.4f} {delta:+18.4f}")


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not in PATH")
async def test_skip_vs_no_skip_when_already_near_target(capsys):
    """|input−target| 在默认容差内：skip>0 会 copy；skip=0 仍重编码，probe 可能更接近 target。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        _make_synthetic_mp4(src, seconds=6.0, fps=24)
        base = (await get_video_info(src))["duration"]
        target = base - 0.012
        assert abs(base - target) < 0.02

        out_skip = os.path.join(tmp, "out_default_skip.mp4")
        out_force = os.path.join(tmp, "out_force.mp4")

        await trim_video(src, out_skip, target, mode="trim_only", skip_if_within_sec=0.02)
        await trim_video(src, out_force, target, mode="trim_only", skip_if_within_sec=0.0)

        d_skip = (await get_video_info(out_skip))["duration"]
        d_force = (await get_video_info(out_force))["duration"]

        with capsys.disabled():
            print("\n--- near-target: default skip vs force ---")
            print(f"input_probe={base:.4f} target={target:.4f} |input-target|={abs(base-target):.4f}")
            print(f"skip=0.02 (copy)   out_probe={d_skip:.4f} Δ={d_skip - target:+.4f}")
            print(f"skip=0   (re-enc)  out_probe={d_force:.4f} Δ={d_force - target:+.4f}")

        assert abs(d_skip - base) < 0.02
        assert abs(d_force - target) < 0.12


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not in PATH")
async def test_trim_only_short_source_no_pad_stays_short(capsys):
    """短于 target + trim_only：无法垫片，输出时长≈输入（与 lipsync 合并默认 trim_only 行为一致）。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        _make_synthetic_mp4(src, seconds=2.5, fps=24)
        in_dur = (await get_video_info(src))["duration"]
        target = 2.6
        out = os.path.join(tmp, "out.mp4")
        await trim_video(src, out, target, mode="trim_only", skip_if_within_sec=0.0)
        out_dur = (await get_video_info(out))["duration"]
        delta = out_dur - target
        with capsys.disabled():
            print("\n--- trim_only, source shorter than target (no pad) ---")
            print(f"in_probe={in_dur:.4f} target={target:.4f} out_probe={out_dur:.4f} Δ(out-target)={delta:+.4f}")
        assert out_dur < target - 0.02
        assert abs(out_dur - in_dur) < 0.15


@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not in PATH")
async def test_pad_or_trim_short_source_reaches_target_with_skip_zero(capsys):
    """短于 target + pad_or_trim + skip=0：仍应补黑到 target 附近。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        _make_synthetic_mp4(src, seconds=2.5, fps=24)
        target = 2.6
        out = os.path.join(tmp, "out.mp4")
        await trim_video(src, out, target, mode="pad_or_trim", skip_if_within_sec=0.0)
        out_dur = (await get_video_info(out))["duration"]
        delta = out_dur - target
        with capsys.disabled():
            print("\n--- pad_or_trim, source shorter, skip=0 ---")
            print(f"target={target:.4f} out_probe={out_dur:.4f} Δ={delta:+.4f}")
        assert abs(delta) < 0.15
