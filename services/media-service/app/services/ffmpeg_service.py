import asyncio
import json
import logging
import math
import os
import re
import uuid
from pathlib import Path, PureWindowsPath
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_job_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _job_semaphore
    if _job_semaphore is None:
        _job_semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
    return _job_semaphore


async def run_ffmpeg(cmd: list[str], timeout: int = None) -> tuple[int, str, str]:
    """Run an FFmpeg command with concurrency limiting."""
    if timeout is None:
        timeout = settings.request_timeout
    async with _get_semaphore():
        logger.info("ffmpeg cmd: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"FFmpeg timeout after {timeout}s")
        return proc.returncode, stdout.decode(), stderr.decode()


def _escape_subtitle_filter_path(path: str) -> str:
    # Keep an absolute Windows drive path intact even when the command is being
    # assembled by a POSIX test/compatibility environment.
    if re.match(r"^[A-Za-z]:[\\/]", path):
        value = path.replace("\\", "/")
    else:
        value = os.path.abspath(path).replace("\\", "/")
    return (
        value.replace(":", r"\:")
        .replace("'", r"\'")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace(",", r"\,")
        .replace(";", r"\;")
    )


_CJK_FONT_CANDIDATES = (
    # Windows. NotoSansSC-VF's family name is "Noto Sans SC", not
    # "Noto Sans CJK SC"; using the latter silently falls back to a font that
    # may have no Chinese glyphs.
    ("Noto Sans SC", r"C:\Windows\Fonts\NotoSansSC-VF.ttf"),
    ("Microsoft YaHei", r"C:\Windows\Fonts\msyh.ttc"),
    ("SimHei", r"C:\Windows\Fonts\simhei.ttf"),
    ("DengXian", r"C:\Windows\Fonts\Deng.ttf"),
    # WSL can use the same host fonts through the mounted Windows drive.
    ("Noto Sans SC", "/mnt/c/Windows/Fonts/NotoSansSC-VF.ttf"),
    ("Microsoft YaHei", "/mnt/c/Windows/Fonts/msyh.ttc"),
    ("SimHei", "/mnt/c/Windows/Fonts/simhei.ttf"),
    # Debian/Ubuntu fonts-noto-cjk and common alternative layouts.
    ("Noto Sans CJK SC", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("Noto Sans CJK SC", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ("Noto Sans CJK SC", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("WenQuanYi Zen Hei", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    # macOS.
    ("PingFang SC", "/System/Library/Fonts/PingFang.ttc"),
)


def _resolve_subtitle_font(requested_name: Optional[str] = None) -> tuple[str, Optional[str], str]:
    """Resolve a usable subtitle font and the directory libass must scan.

    libass does not fail when a requested family is absent: it silently picks a
    fallback, which can turn every CJK character into a rectangle. Auto mode is
    intentionally strict so a bad captioned video is never reported as success.
    """
    configured_name = (requested_name or settings.subtitle_font_name or "").strip()
    configured_dir = (settings.subtitle_fonts_dir or "").strip()
    if configured_name:
        resolved_dir = str(Path(configured_dir).expanduser().resolve()) if configured_dir else None
        if resolved_dir and not Path(resolved_dir).is_dir():
            raise RuntimeError(
                f"Configured SUBTITLE_FONTS_DIR does not exist: {resolved_dir}"
            )
        return configured_name, resolved_dir, "configured" if settings.subtitle_font_name else "request"

    if configured_dir:
        resolved_dir = str(Path(configured_dir).expanduser().resolve())
        if not Path(resolved_dir).is_dir():
            raise RuntimeError(
                f"Configured SUBTITLE_FONTS_DIR does not exist: {resolved_dir}"
            )

    for family, font_path in _CJK_FONT_CANDIDATES:
        candidate = Path(font_path)
        if candidate.is_file():
            if re.match(r"^[A-Za-z]:[\\/]", font_path):
                parent = str(PureWindowsPath(font_path).parent)
            else:
                parent = str(candidate.parent)
            return family, parent, str(candidate)

    raise RuntimeError(
        "No CJK subtitle font was found. Install fonts-noto-cjk, or set "
        "SUBTITLE_FONT_NAME and SUBTITLE_FONTS_DIR to a font containing Chinese glyphs."
    )


async def burn_subtitles(
    video_path: str,
    subtitle_path: str,
    output_path: str,
    *,
    style_preset: str = "clean",
    position: str = "bottom-safe",
    font_name: Optional[str] = None,
) -> dict:
    """Burn an SRT/VTT/ASS subtitle file into a new H.264 MP4."""
    info = await get_video_info(video_path)
    height = max(240, int(info.get("height") or 1080))
    width = max(320, int(info.get("width") or round(height * 16 / 9)))
    # libass lays SRT text out on its legacy 384x288 script canvas. Passing
    # pixel-sized values (for example 56 at 1080p) therefore scales them by
    # roughly 1080/288 and creates enormous, center-looking captions. Keep the
    # preset values in ASS canvas units and declare the real source size.
    presets = {
        "short-video-bold": {"font_size": 18, "outline": 1.25, "bold": 1},
        "clean": {"font_size": 16, "outline": 1.0, "bold": 0},
        "minimal": {"font_size": 14, "outline": 0.75, "bold": 0},
    }
    preset = presets.get(style_preset, presets["clean"])
    alignment = {"bottom-safe": 2, "bottom": 2, "center": 5, "top": 8}.get(position, 2)
    ass_margin_v = {"bottom-safe": 16, "bottom": 8, "center": 0, "top": 14}.get(position, 16)
    resolved_font, fonts_dir, font_source = _resolve_subtitle_font(font_name)
    safe_font = re.sub(r"[^A-Za-z0-9 _-]", "", resolved_font).strip()
    if not safe_font:
        raise RuntimeError("The resolved subtitle font name is invalid")
    ass_font_size = preset["font_size"]
    force_style = ",".join([
        f"FontName={safe_font}",
        f"FontSize={ass_font_size}",
        "PrimaryColour=&H00FFFFFF",
        "OutlineColour=&H00000000",
        "BackColour=&H80000000",
        f"Bold={preset['bold']}",
        "BorderStyle=1",
        f"Outline={preset['outline']}",
        "Shadow=0",
        f"Alignment={alignment}",
        f"MarginV={ass_margin_v}",
    ])
    escaped_path = _escape_subtitle_filter_path(subtitle_path)
    filter_options = [
        f"filename='{escaped_path}'",
        f"original_size={width}x{height}",
    ]
    if fonts_dir:
        filter_options.append(f"fontsdir='{_escape_subtitle_filter_path(fonts_dir)}'")
    filter_options.append(f"force_style='{force_style}'")
    video_filter = "subtitles=" + ":".join(filter_options)
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", video_filter,
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "copy", "-movflags", "+faststart", output_path,
    ]
    code, _, stderr = await run_ffmpeg(cmd)
    if code != 0:
        raise RuntimeError(f"FFmpeg subtitle burn failed: {stderr[-2000:]}")
    return {
        "preset": style_preset,
        "position": position,
        "font_name": safe_font,
        "font_source": font_source,
        "fonts_dir": fonts_dir,
        "font_size": round(ass_font_size * height / 288),
        "ass_font_size": ass_font_size,
        "outline": preset["outline"],
        "margin_v": round(ass_margin_v * height / 288),
        "ass_margin_v": ass_margin_v,
        "source_size": f"{width}x{height}",
    }


async def ffprobe_json(file_path: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", file_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return json.loads(stdout.decode())


async def get_video_duration_decoded(file_path: str, timeout: Optional[int] = None) -> Optional[float]:
    """Get the video's true duration by full decoding (matching the player). Same standard as audio: ffmpeg -f null - and parse time=."""
    if timeout is None:
        timeout = settings.request_timeout
    # do not add -v error, otherwise stderr has no time= progress lines
    cmd = ["ffmpeg", "-y", "-i", file_path, "-f", "null", "-"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        sec = _parse_ffmpeg_time_line(stderr.decode())
        if sec is not None and sec > 0:
            return sec
    except (asyncio.TimeoutError, FileNotFoundError, OSError) as e:
        logger.warning("get_video_duration_decoded failed: %s", e)
    return None


async def get_video_info(file_path: str) -> dict:
    data = await ffprobe_json(file_path)
    fmt = data.get("format", {})
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video_stream:
        raise ValueError(f"No video stream found: {file_path}")
    duration_fallback = float(fmt.get("duration", 0))
    decoded_duration = await get_video_duration_decoded(file_path)
    duration = decoded_duration if (decoded_duration is not None and decoded_duration > 0) else duration_fallback
    if decoded_duration is not None and decoded_duration > 0:
        logger.info("video duration (decoded): %.3fs", duration)
    elif duration_fallback > 0:
        logger.info("video duration (ffprobe fallback): %.3fs", duration_fallback)
    fps_val = _parse_fps(video_stream.get("r_frame_rate", "25/1"))
    # nb_frames: prefer the frame count from the container header (concat -c copy stacks frames, so the result frame count = sum of segment frame counts);
    # fall back to round(duration*fps) when missing/abnormal. For upstream "integer frame" drift prediction.
    nb_frames_raw = video_stream.get("nb_frames")
    try:
        nb_frames = int(nb_frames_raw) if nb_frames_raw not in (None, "", "N/A") else 0
    except (ValueError, TypeError):
        nb_frames = 0
    if nb_frames <= 0:
        nb_frames = round(duration * fps_val) if fps_val > 0 else 0
    try:
        stream_duration = float(video_stream.get("duration") or 0)
    except (TypeError, ValueError):
        stream_duration = 0.0
    frame_duration = (nb_frames / fps_val) if nb_frames > 0 and fps_val > 0 else 0.0
    video_duration = stream_duration if stream_duration > 0 else frame_duration
    return {
        "duration": duration,
        "video_duration": video_duration or duration,
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": fps_val,
        "nb_frames": nb_frames,
        "codec": video_stream.get("codec_name"),
        "pix_fmt": video_stream.get("pix_fmt"),
        "has_audio": audio_stream is not None,
        "time_base": video_stream.get("time_base", ""),
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "audio_sample_rate": int(audio_stream.get("sample_rate") or 0) if audio_stream else 0,
        "audio_channels": int(audio_stream.get("channels") or 0) if audio_stream else 0,
        "audio_channel_layout": audio_stream.get("channel_layout", "") if audio_stream else "",
        "audio_time_base": audio_stream.get("time_base", "") if audio_stream else "",
    }


# Parse the last time=HH:MM:SS.xx from ffmpeg -f null - stderr to get the true decoded duration (seconds)
# Used when MP3 etc. metadata is inaccurate (e.g. "Estimating duration from bitrate") to get a player-consistent duration
_TIME_RE = re.compile(r"time=(\d+):(\d{2}):(\d{2})\.(\d+)")

def _parse_ffmpeg_time_line(stderr: str) -> Optional[float]:
    matches = list(_TIME_RE.finditer(stderr))
    if not matches:
        return None
    m = matches[-1]
    h, mm, ss, frac = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    frac = (frac + "000000")[:6]
    return h * 3600 + mm * 60 + ss + int(frac) / 1_000_000.0


async def get_audio_duration_decoded(file_path: str, timeout: Optional[int] = None) -> Optional[float]:
    """Get the audio's true duration by full decoding (matching the player). Use this when metadata is inaccurate (e.g. VBR/junk)."""
    if timeout is None:
        timeout = settings.request_timeout
    # do not add -v error, otherwise stderr has no time= progress lines and the true duration cannot be parsed
    cmd = ["ffmpeg", "-y", "-i", file_path, "-vn", "-f", "null", "-"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        sec = _parse_ffmpeg_time_line(stderr.decode())
        if sec is not None and sec > 0:
            return sec
    except (asyncio.TimeoutError, FileNotFoundError, OSError) as e:
        logger.warning("get_audio_duration_decoded failed: %s", e)
    return None


async def get_audio_duration(file_path: str) -> float:
    """Audio duration (seconds). Prefer the true decoded duration, fall back to ffprobe metadata on failure."""
    decoded = await get_audio_duration_decoded(file_path)
    if decoded is not None and decoded > 0:
        logger.info("audio duration (decoded): %.3fs", decoded)
        return decoded
    data = await ffprobe_json(file_path)
    fallback = float(data.get("format", {}).get("duration", 0))
    if decoded is None and fallback > 0:
        logger.info("audio duration (ffprobe fallback): %.3fs", fallback)
    return fallback


async def _ffprobe_keyframe_times_one_field(file_path: str, frame_entries: str) -> list[float]:
    """ffprobe keyframe-only lines; frame_entries such as frame=pkt_pts_time."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-skip_frame",
        "nokey",
        "-show_entries",
        frame_entries,
        "-of",
        "csv=p=0",
        file_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("keyframe probe %s failed: %s", frame_entries, stderr.decode()[:300])
        return []
    out: list[float] = []
    for line in stdout.decode().splitlines():
        s = line.strip()
        if not s or s == "N/A":
            continue
        first = s.split(",", 1)[0].strip()
        if first == "N/A":
            continue
        try:
            out.append(float(first))
        except ValueError:
            continue
    return out


async def _list_keyframe_pts_from_packets(file_path: str) -> list[float]:
    """On some CI/ffmpeg versions frame=pkt_pts_time is all N/A; fall back to packet key_frame+pts_time."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "packet=pts_time,key_frame",
        "-of",
        "csv=p=0",
        file_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("keyframe packet probe failed: %s", stderr.decode()[:300])
        return []
    out: list[float] = []
    for line in stdout.decode().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        pts_s, kf_s = parts[0], parts[1]
        if kf_s != "1" or pts_s in ("", "N/A"):
            continue
        try:
            out.append(float(pts_s))
        except ValueError:
            continue
    return out


async def _list_keyframe_pts_times(file_path: str) -> list[float]:
    """Keyframe timestamps (seconds); multi-field/packet-level probing, to avoid hybrid failure when pkt_pts_time is all empty on CI."""
    for entries in (
        "frame=pkt_pts_time",
        "frame=best_effort_timestamp_time",
        "frame=pkt_dts_time",
    ):
        got = await _ffprobe_keyframe_times_one_field(file_path, entries)
        if got:
            return sorted(set(got))
    got = await _list_keyframe_pts_from_packets(file_path)
    return sorted(set(got))


def _last_keyframe_time_at_or_before(times: list[float], before_sec: float) -> Optional[float]:
    last: Optional[float] = None
    for t in times:
        if t <= before_sec + 1e-6:
            last = t
        else:
            break
    return last


async def _trim_shorten_hybrid_copy_tail_encode(
    input_path: str,
    output_path: str,
    target_duration: float,
) -> None:
    """Truncate: 0..K -c copy + K..target ultrafast + concat. Must succeed in one pass; raises on failure (no trim_video fallback layer)."""
    kf_times = await _list_keyframe_pts_times(input_path)
    kf = _last_keyframe_time_at_or_before(kf_times, target_duration)
    if kf is None:
        kf = 0.0
    tail = target_duration - kf
    # sub-frame tail detection: if tail < one frame duration, p2's -t parameter makes ffmpeg encode 0 frames (empty file).
    # use -frames:v 1 instead to ensure exactly 1 frame (~1/fps), avoiding p2 being empty and the output being ~1 frame short.
    _fps_info = await get_video_info(input_path)
    _fps = float(_fps_info.get("fps", 24.0))
    _one_frame = 1.0 / max(_fps, 1.0)
    _use_frames_v1 = 1e-4 < tail < _one_frame
    base = output_path + f".hybrid_{uuid.uuid4().hex[:8]}"
    p1 = base + "_p1.mp4"
    p2 = base + "_p2.mp4"
    lst = base + "_list.txt"
    try:
        if tail <= 1e-4:
            rc0, _, e0 = await run_ffmpeg(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    input_path,
                    "-to",
                    str(target_duration),
                    "-map",
                    "0:v",
                    "-an",
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    output_path,
                ]
            )
            if rc0 != 0:
                rc0b, _, e0b = await run_ffmpeg(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        input_path,
                        "-t",
                        str(target_duration),
                        "-map",
                        "0:v",
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        output_path,
                    ]
                )
                if rc0b != 0:
                    raise RuntimeError(
                        f"trim_shorten_hybrid: tail~0 copy+encode failed: {e0[:200]} | {e0b[:300]}"
                    )
            logger.info(
                "trim_shorten_hybrid: tail~0 target=%.4f", target_duration
            )
            return

        if kf > 1e-3:
            cmd1 = [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-to",
                str(kf),
                "-map",
                "0:v",
                "-an",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                p1,
            ]
            rc1, _, e1 = await run_ffmpeg(cmd1)
            if rc1 != 0:
                raise RuntimeError(
                    f"trim_shorten_hybrid: part1 copy failed: {e1[:500]}"
                )
        else:
            p1 = ""

        # sub-frame tail: use -frames:v 1 to guarantee exactly 1 frame output
        _duration_or_frames = ["-frames:v", "1"] if _use_frames_v1 else ["-t", str(tail)]
        cmd2 = [
            "ffmpeg",
            "-y",
            "-ss",
            str(kf),
            "-i",
            input_path,
            *_duration_or_frames,
            "-map",
            "0:v",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-movflags",
            "+faststart",
            p2,
        ]
        rc2, _, e2 = await run_ffmpeg(cmd2)
        if rc2 != 0:
            raise RuntimeError(
                f"trim_shorten_hybrid: part2 encode failed: {e2[:500]}"
            )

        if p1 and os.path.isfile(p1) and os.path.getsize(p1) > 0:
            with open(lst, "w") as f:
                _esc = lambda s: s.replace("'", "'\\''")
                f.write(f"file '{_esc(p1)}'\n")
                f.write(f"file '{_esc(p2)}'\n")
            cmd3 = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                lst,
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                output_path,
            ]
            rc3, _, e3 = await run_ffmpeg(cmd3)
            if rc3 != 0:
                logger.warning(
                    "trim_shorten_hybrid: concat demuxer failed, filter concat: %s",
                    e3[:400],
                )
                rc4, _, e4 = await run_ffmpeg(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        p1,
                        "-i",
                        p2,
                        "-filter_complex",
                        "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                        "-map",
                        "[v]",
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        output_path,
                    ]
                )
                if rc4 != 0:
                    raise RuntimeError(
                        f"trim_shorten_hybrid: concat filter failed: {e4[:500]}"
                    )
        else:
            import shutil

            shutil.copy2(p2, output_path)
            logger.info(
                "trim_shorten_hybrid: kf≈0, single tail encode only tail=%.4fs", tail
            )
        logger.info(
            "trim_shorten_hybrid: ok kf=%.4f tail=%.4fs (target=%.4f)",
            kf,
            tail,
            target_duration,
        )
    finally:
        for p in (p1, p2, lst):
            if p and os.path.isfile(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


async def _trim_extend_freeze_concat(
    input_path: str,
    output_path: str,
    target_duration: float,
    width: int,
    height: int,
    fps: float = 24.0,
) -> None:
    """Clip shorter than target with a small gap: main clip copies video track only; then compute the still-frame length from main's measured duration, to avoid total-length drift caused by probe/copy duration mismatch."""
    base = output_path + f".ext_{uuid.uuid4().hex[:8]}"
    main_v = base + "_main.mp4"
    frame = base + "_last.jpg"
    still = base + "_still.mp4"
    lst = base + "_list.txt"
    chop_tmp: Optional[str] = None
    try:
        rc, _, e = await run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-map",
                "0:v",
                "-an",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                main_v,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"extend_freeze: main video copy failed: {e[:500]}")
        d_main = (await get_video_info(main_v))["duration"]
        gap_sec = target_duration - d_main
        if gap_sec <= 1e-4:
            import shutil
            shutil.copy2(main_v, output_path)
            logger.info("extend_freeze: main already >= target (d_main=%.4f T=%.4f)", d_main, target_duration)
            return
        if gap_sec > settings.trim_extend_freeze_max_sec + 1e-3:
            await _trim_extend_tail_slow_or_uniform(
                main_v, output_path, d_main, target_duration
            )
            return
        rc, _, e = await run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-sseof",
                "-3",
                "-i",
                input_path,
                "-vframes",
                "1",
                "-q:v",
                "3",
                frame,
            ]
        )
        if rc != 0 or not os.path.isfile(frame):
            raise RuntimeError(f"extend_freeze: last frame extract failed: {e[:500]}")
        fps_str = str(max(1, round(fps)))
        rc, _, e = await run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-framerate",
                fps_str,
                "-i",
                frame,
                "-t",
                str(gap_sec),
                "-vf",
                f"scale={width}:{height}",
                "-r",
                fps_str,
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-g",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                still,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"extend_freeze: still clip failed: {e[:500]}")
        # use filter_complex concat instead of -c copy concat, to avoid PTS-offset miscalculation and freeze frames
        # when main_v and still have different time bases (time_base) (e.g. 1/24000 vs 1/12288),
        # which stack at the same instant and make the output duration equal to the original video.
        # filter_complex handles time-base conversion automatically, ensuring the still frame is appended at the correct position after main_v.
        # -g 1 ensures the output is all keyframes (including the freeze section), so a later trim_only can land frames precisely.
        rc, _, e = await run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                main_v,
                "-i",
                still,
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0[out]",
                "-map",
                "[out]",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-g",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                output_path,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"extend_freeze: concat filter failed: {e[:500]}")
        d_out = (await get_video_info(output_path))["duration"]
        if d_out > target_duration + 0.04:
            chop = base + "_chop.mp4"
            chop_tmp = chop
            await _trim_shorten_hybrid_copy_tail_encode(
                output_path, chop, target_duration
            )
            os.replace(chop, output_path)
        logger.info(
            "extend_freeze: target=%.4fs still_req=%.4fs (filter concat + g1, avoid timebase mismatch)",
            target_duration,
            gap_sec,
        )
    finally:
        for p in (main_v, frame, still, lst, chop_tmp):
            if p and os.path.isfile(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


async def _trim_extend_tail_slow_or_uniform(
    input_path: str,
    output_path: str,
    d: float,
    target_duration: float,
) -> None:
    """Gap larger than the freeze cap: prefer slowing only the tail (L+gap)/L; if not possible, setpts=T/d over the whole clip. Both output no audio track."""
    g = target_duration - d
    if g <= 0:
        import shutil
        shutil.copy2(input_path, output_path)
        return
    L = min(
        settings.trim_extend_tail_max_sec,
        max(settings.trim_extend_tail_min_sec, d * settings.trim_extend_tail_fraction),
    )
    head_end = d - L
    if head_end <= 0.05:
        L = max(0.25, d * 0.45)
        head_end = d - L
    slow = (L + g) / L
    max_sf = settings.trim_extend_tail_max_slow_factor
    if slow > max_sf:
        L = g / (max_sf - 1.0) + 1e-6
        L = min(max(L, settings.trim_extend_tail_min_sec), d * 0.98)
        head_end = d - L
        if head_end <= 0.02:
            L = max(0.2, d * 0.5)
            head_end = d - L
        slow = (L + g) / L
    use_uniform = slow > max_sf + 0.05 or head_end < 0.01
    if use_uniform:
        fac = target_duration / d
        rc, _, e = await run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-vf",
                f"setpts={fac}*PTS",
                "-map",
                "0:v",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                output_path,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"extend_tail_slow: uniform setpts failed: {e[:500]}")
        logger.info(
            "extend_tail_slow: uniform setpts factor=%.6f (d=%.4f T=%.4f)",
            fac,
            d,
            target_duration,
        )
        return
    h_end = head_end
    fc = (
        f"[0:v]trim=end={h_end},setpts=PTS-STARTPTS[v1];"
        f"[0:v]trim=start={h_end},setpts=(PTS-STARTPTS)*{slow}[v2];"
        f"[v1][v2]concat=n=2:v=1:a=0[out]"
    )
    rc, _, e = await run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-filter_complex",
            fc,
            "-map",
            "[out]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            output_path,
        ]
    )
    if rc != 0:
        raise RuntimeError(f"extend_tail_slow: filter failed: {e[:500]}")
    logger.info(
        "extend_tail_slow: head_end=%.4f L=%.4f slow=%.6f gap=%.4f",
        h_end,
        L,
        slow,
        g,
    )


async def trim_video(
    input_path: str,
    output_path: str,
    target_duration: float,
    mode: str = "pad_or_trim",
    skip_if_within_sec: float = 0.02,
):
    info = await get_video_info(input_path)
    current_dur = info["duration"]
    duration_diff = current_dur - target_duration
    logger.info(
        "trim_video: mode=%s probe=%.4fs target=%.4fs Δ=%+.4fs",
        mode,
        current_dur,
        target_duration,
        duration_diff,
    )

    # the tolerance must be smaller than one frame duration at the lowest frame rate (24fps) (0.042s), otherwise +/-1 frame would be skipped.
    # skip_if_within_sec=0: never skip, useful for stress-testing "forced -t re-encode" probe deviation relative to target.
    if skip_if_within_sec > 0 and abs(current_dur - target_duration) < skip_if_within_sec:
        import shutil
        shutil.copy2(input_path, output_path)
        return

    if current_dur > target_duration:
        # hybrid must succeed on its own (hardened probing/concat); no "re-encode the whole clip on failure".
        # when Settings.trim_shorten_hybrid=false, only whole-clip -t ultrafast.
        if settings.trim_shorten_hybrid:
            await _trim_shorten_hybrid_copy_tail_encode(
                input_path, output_path, target_duration
            )
            return
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-t", str(target_duration),
            "-c:v", "libx264", "-preset", "ultrafast",
            "-an", "-movflags", "+faststart",
            output_path,
        ]
    elif mode == "freeze_or_tail_slow":
        gap = target_duration - current_dur
        if gap <= 0:
            import shutil
            shutil.copy2(input_path, output_path)
            return
        if gap <= settings.trim_extend_freeze_max_sec:
            logger.info(
                "trim_video extend: gap=%.4fs ≤ freeze_max=%.4fs → 末帧静帧延长（非循环）",
                gap,
                settings.trim_extend_freeze_max_sec,
            )
            await _trim_extend_freeze_concat(
                input_path,
                output_path,
                target_duration,
                info["width"],
                info["height"],
                fps=float(info.get("fps", 24.0)),
            )
        else:
            logger.info(
                "trim_video extend: gap=%.4fs > freeze_max=%.4fs → 尾部减速/整片 setpts（非循环）",
                gap,
                settings.trim_extend_freeze_max_sec,
            )
            await _trim_extend_tail_slow_or_uniform(
                input_path, output_path, current_dur, target_duration
            )
        return
    elif mode == "pad_or_trim":
        pad_dur = target_duration - current_dur
        w, h = info["width"], info["height"]
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={info['fps']:.0f}:d={pad_dur}",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]",
            "-movflags", "+faststart",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-t", str(target_duration),
            "-c", "copy", "-movflags", "+faststart",
            output_path,
        ]

    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg trim failed: {stderr[:500]}")


def _ffmpeg_error_tail(stderr: str, limit: int = 800) -> str:
    text = stderr or ""
    if len(text) <= limit:
        return text
    return text[-limit:]


def _concat_vfilter(
    index: int,
    tw: int,
    th: int,
    fps_filter: str,
) -> str:
    # fps must come *after* settb/setpts. FFmpeg 7.1 xfade treats a stream whose
    # last timebase rewrite is settb=AVTB as rate 1/0 and refuses to configure.
    return (
        f"[{index}:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,"
        f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"settb=AVTB,setpts=PTS-STARTPTS{fps_filter}[v{index}]"
    )


def _concat_afilter(index: int, duration: float, has_audio: bool) -> str:
    if has_audio:
        return (
            f"[{index}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"aresample=async=1:first_pts=0,apad,atrim=duration={duration:.9f},"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )
    return (
        "anullsrc=sample_rate=44100:channel_layout=stereo,"
        f"atrim=duration={duration:.9f},asetpts=PTS-STARTPTS[a{index}]"
    )


async def concat_videos(
    input_paths: list[str],
    output_path: str,
    normalize: bool = True,
    transition_duration: float = 0.0,
    _force_transcode: bool = False,
):
    if not input_paths:
        raise ValueError("No input files for concat")

    transition_duration = max(0.0, min(1.0, float(transition_duration or 0.0)))
    if transition_duration > 0 and len(input_paths) > 1:
        # xfade/acrossfade require decoded streams, so stream-copy concat is not valid.
        normalize = True

    BATCH_SIZE = 8
    infos = None

    # A requested normalization is a compatibility guarantee, not a requirement to
    # transcode already-identical streams.  Exact matches (including HEVC/Main10
    # Seedance clips) can be concatenated losslessly in seconds. Every clip must
    # have a compatible audio stream; otherwise normalization adds duration-matched
    # silent AAC for clips without audio before concatenating all A/V streams.
    if not _force_transcode and transition_duration <= 0:
        infos = [await get_video_info(p) for p in input_paths]
        ref = infos[0]
        audio_flags = [bool(info.get("has_audio")) for info in infos]
        audio_uniform = all(audio_flags)
        video_copy_safe = all(
            info.get("codec") == ref.get("codec")
            and info.get("pix_fmt") == ref.get("pix_fmt")
            and info.get("width") == ref.get("width")
            and info.get("height") == ref.get("height")
            and abs(info.get("fps", 0) - ref.get("fps", 0)) < 0.001
            for info in infos
        )
        audio_copy_safe = all(audio_flags) and all(
            info.get("audio_codec") == ref.get("audio_codec")
            and info.get("audio_sample_rate") == ref.get("audio_sample_rate")
            and info.get("audio_channels") == ref.get("audio_channels")
            and info.get("audio_channel_layout") == ref.get("audio_channel_layout")
            and info.get("audio_time_base") == ref.get("audio_time_base")
            for info in infos
        )
        copy_safe = audio_uniform and video_copy_safe and audio_copy_safe
        if copy_safe:
            if normalize:
                logger.info(
                    "concat_videos normalize fast-path: streams already compatible; "
                    "using lossless copy"
                )
            normalize = False
            # time_base mismatch causes timestamp corruption in -c copy concat;
            # re-mux outliers to the most common time_base before proceeding.
            time_bases = [info.get("time_base", "") for info in infos]
            from collections import Counter
            tb_counts = Counter(tb for tb in time_bases if tb)
            if len(tb_counts) > 1:
                target_tb = tb_counts.most_common(1)[0][0]
                parts = target_tb.split("/")
                ts_val = int(parts[1]) if len(parts) == 2 else 24000
                mismatched = [(i, p) for i, (p, tb) in enumerate(zip(input_paths, time_bases)) if tb != target_tb]
                logger.warning(
                    "concat_videos: %d/%d files have different time_base, re-muxing to %s",
                    len(mismatched), len(input_paths), target_tb,
                )
                for idx, orig_path in mismatched:
                    fixed_path = orig_path + ".tb_fix.mp4"
                    fix_cmd = [
                        "ffmpeg", "-y", "-i", orig_path,
                        "-c", "copy", "-video_track_timescale", str(ts_val),
                        "-movflags", "+faststart", fixed_path,
                    ]
                    fix_rc, _, fix_err = await run_ffmpeg(fix_cmd)
                    if fix_rc == 0:
                        os.rename(fixed_path, orig_path)
                        infos[idx] = await get_video_info(orig_path)
                    else:
                        logger.error("time_base re-mux failed for %s: %s", orig_path, fix_err[:200])
            logger.info(
                "concat_videos copy-safe: %d videos %s/%s audio=%s %dx%d fps=%.1f",
                len(infos),
                ref.get("codec"),
                ref.get("pix_fmt"),
                "yes" if all(audio_flags) else "no",
                ref.get("width", 0),
                ref.get("height", 0),
                ref.get("fps", 0),
            )
        else:
            normalize = True
            _bad = next(
                (i for i, info in enumerate(infos)
                 if info.get("codec") != ref.get("codec")
                 or info.get("pix_fmt") != ref.get("pix_fmt")
                 or info.get("width") != ref.get("width")
                 or info.get("height") != ref.get("height")
                 or abs(info.get("fps", 0) - ref.get("fps", 0)) >= 0.001
                 or (
                     bool(info.get("has_audio"))
                     and (
                         info.get("audio_codec") != ref.get("audio_codec")
                         or info.get("audio_sample_rate") != ref.get("audio_sample_rate")
                         or info.get("audio_channels") != ref.get("audio_channels")
                         or info.get("audio_channel_layout") != ref.get("audio_channel_layout")
                         or info.get("audio_time_base") != ref.get("audio_time_base")
                     )
                 )
                 or not audio_uniform),
                0,
            )
            _bi = infos[_bad]
            logger.warning(
                "concat_videos FALLBACK normalize=True: video[%d]/%d not copy-safe "
                "(codec=%s pix_fmt=%s audio=%s %dx%d fps=%.1f) vs ref (codec=%s %dx%d fps=%.1f) "
                "audio_uniform=%s",
                _bad, len(infos),
                _bi.get("codec"), _bi.get("pix_fmt"), _bi.get("has_audio"),
                _bi.get("width", 0), _bi.get("height", 0), _bi.get("fps", 0),
                ref.get("codec"), ref.get("width", 0), ref.get("height", 0), ref.get("fps", 0),
                audio_uniform,
            )

    if normalize:
        if infos is None:
            infos = [await get_video_info(p) for p in input_paths]
        tw, th, target_fps = _pick_reference_params(infos)
        logger.info(
            "concat_videos normalize ref: %dx%d fps=%.2f (from %d videos)",
            tw, th, target_fps, len(infos),
        )
    else:
        tw, th, target_fps = None, None, None

    audio_presence = [bool(i.get("has_audio")) for i in (infos or [])]
    keep_audio = bool(infos)
    video_durations = [
        float(info.get("video_duration") or info.get("duration") or 0.0)
        for info in (infos or [])
    ]

    if normalize and tw and th and len(input_paths) > BATCH_SIZE and transition_duration <= 0:
        await _concat_normalize_batched(
            input_paths,
            output_path,
            tw,
            th,
            BATCH_SIZE,
            target_fps,
            keep_audio=keep_audio,
            video_durations=video_durations,
            audio_presence=audio_presence,
        )
        return

    list_file = output_path + ".filelist.txt"
    with open(list_file, "w") as f:
        for p in input_paths:
            f.write(f"file '{p}'\n")

    if normalize and tw and th:
        fps_filter = f",fps={target_fps:.6f}" if target_fps else ""
        if any(duration <= 0 for duration in video_durations):
            raise RuntimeError("Cannot concatenate a clip with unknown video duration")
        filter_parts = []
        for i in range(len(input_paths)):
            filter_parts.append(_concat_vfilter(i, tw, th, fps_filter))
        if keep_audio:
            for i in range(len(input_paths)):
                filter_parts.append(
                    _concat_afilter(i, video_durations[i], audio_presence[i])
                )
            if transition_duration > 0:
                blend = min(transition_duration, min(video_durations) / 2.0)
                current_duration = video_durations[0]
                video_label = "v0"
                audio_label = "a0"
                for i in range(1, len(input_paths)):
                    next_video_label = f"vx{i}"
                    next_audio_label = f"ax{i}"
                    offset = max(0.0, current_duration - blend)
                    filter_parts.append(
                        f"[{video_label}][v{i}]xfade=transition=fade:duration={blend:.9f}:"
                        f"offset={offset:.9f}[{next_video_label}]"
                    )
                    filter_parts.append(
                        f"[{audio_label}][a{i}]acrossfade=d={blend:.9f}:c1=tri:c2=tri"
                        f"[{next_audio_label}]"
                    )
                    video_label = next_video_label
                    audio_label = next_audio_label
                    current_duration += video_durations[i] - blend
                filter_parts.extend([
                    f"[{video_label}]null[outv]",
                    f"[{audio_label}]anull[outa]",
                ])
                filter_str = ";".join(filter_parts)
            else:
                v_in = "".join(f"[v{i}][a{i}]" for i in range(len(input_paths)))
                filter_str = (
                    ";".join(filter_parts)
                    + f";{v_in}concat=n={len(input_paths)}:v=1:a=1[outv][outa]"
                )
            cmd = ["ffmpeg", "-y"]
            for p in input_paths:
                cmd.extend(["-i", p])
            cmd.extend([
                "-filter_complex", filter_str,
                "-map", "[outv]", "-map", "[outa]",
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                output_path,
            ])
        else:
            if transition_duration > 0:
                blend = min(transition_duration, min(video_durations) / 2.0)
                current_duration = video_durations[0]
                video_label = "v0"
                for i in range(1, len(input_paths)):
                    next_video_label = f"vx{i}"
                    offset = max(0.0, current_duration - blend)
                    filter_parts.append(
                        f"[{video_label}][v{i}]xfade=transition=fade:duration={blend:.9f}:"
                        f"offset={offset:.9f}[{next_video_label}]"
                    )
                    video_label = next_video_label
                    current_duration += video_durations[i] - blend
                filter_parts.append(f"[{video_label}]null[outv]")
                filter_str = ";".join(filter_parts)
            else:
                concat_input = "".join(f"[v{i}]" for i in range(len(input_paths)))
                filter_str = ";".join(filter_parts) + f";{concat_input}concat=n={len(input_paths)}:v=1:a=0[outv]"
            cmd = ["ffmpeg", "-y"]
            for p in input_paths:
                cmd.extend(["-i", p])
            cmd.extend([
                "-filter_complex", filter_str,
                "-map", "[outv]",
                "-c:v", "libx264", "-preset", "fast",
                "-movflags", "+faststart",
                output_path,
            ])
    else:
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ]

    rc, _, stderr = await run_ffmpeg(cmd)
    try:
        os.unlink(list_file)
    except OSError:
        pass
    if rc != 0:
        raise RuntimeError(f"FFmpeg concat failed: {_ffmpeg_error_tail(stderr)}")

    if not normalize and infos and len(input_paths) > 1:
        expected_dur = sum(i["duration"] for i in infos)
        out_info = await get_video_info(output_path)
        actual_dur = out_info["duration"]
        if actual_dur > expected_dur * 1.15:
            logger.warning(
                "concat -c copy timestamp corruption: output=%.2fs expected=%.2fs (%.1fx), re-encoding...",
                actual_dur, expected_dur, actual_dur / expected_dur,
            )
            os.unlink(output_path)
            await concat_videos(
                input_paths,
                output_path,
                normalize=True,
                _force_transcode=True,
            )


async def _concat_normalize_batched(
    input_paths: list[str], output_path: str, tw: int, th: int, batch_size: int,
    target_fps: Optional[float] = None,
    keep_audio: bool = False,
    video_durations: Optional[list[float]] = None,
    audio_presence: Optional[list[bool]] = None,
):
    """Normalize-concat in batches to avoid OOM with large input counts."""
    out_dir = os.path.dirname(output_path)
    batch_outputs = []
    fps_filter = f",fps={target_fps:.6f}" if target_fps else ""

    for batch_idx in range(0, len(input_paths), batch_size):
        batch = input_paths[batch_idx:batch_idx + batch_size]
        batch_out = os.path.join(out_dir, f"_batch{batch_idx}_{uuid.uuid4().hex[:6]}.mp4")

        filter_parts = []
        batch_durations = (video_durations or [])[batch_idx:batch_idx + len(batch)]
        batch_audio_presence = (audio_presence or [])[batch_idx:batch_idx + len(batch)]
        for i in range(len(batch)):
            filter_parts.append(_concat_vfilter(i, tw, th, fps_filter))
        if keep_audio:
            if len(batch_durations) != len(batch) or any(d <= 0 for d in batch_durations):
                raise RuntimeError("Cannot concatenate a clip with unknown video duration")
            if len(batch_audio_presence) != len(batch):
                raise RuntimeError("Cannot determine whether concat inputs contain audio")
            for i in range(len(batch)):
                filter_parts.append(
                    _concat_afilter(i, batch_durations[i], batch_audio_presence[i])
                )
            v_in = "".join(f"[v{i}][a{i}]" for i in range(len(batch)))
            filter_str = (
                ";".join(filter_parts) + f";{v_in}concat=n={len(batch)}:v=1:a=1[outv][outa]"
            )
            cmd = ["ffmpeg", "-y"]
            for p in batch:
                cmd.extend(["-i", p])
            cmd.extend([
                "-filter_complex", filter_str,
                "-map", "[outv]", "-map", "[outa]",
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                batch_out,
            ])
        else:
            concat_input = "".join(f"[v{i}]" for i in range(len(batch)))
            filter_str = ";".join(filter_parts) + f";{concat_input}concat=n={len(batch)}:v=1:a=0[outv]"
            cmd = ["ffmpeg", "-y"]
            for p in batch:
                cmd.extend(["-i", p])
            cmd.extend([
                "-filter_complex", filter_str,
                "-map", "[outv]",
                "-c:v", "libx264", "-preset", "fast",
                "-movflags", "+faststart",
                batch_out,
            ])
        logger.info("concat batch %d-%d (%d files) keep_audio=%s", batch_idx, batch_idx + len(batch), len(batch), keep_audio)
        rc, _, stderr = await run_ffmpeg(cmd)
        if rc != 0:
            raise RuntimeError(f"FFmpeg batch concat failed (batch {batch_idx}): {stderr[:500]}")
        batch_outputs.append(batch_out)

    if len(batch_outputs) == 1:
        os.rename(batch_outputs[0], output_path)
        return

    list_file = output_path + ".batchlist.txt"
    with open(list_file, "w") as f:
        for p in batch_outputs:
            f.write(f"file '{p}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    rc, _, stderr = await run_ffmpeg(cmd)
    for tmp in batch_outputs:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    try:
        os.unlink(list_file)
    except OSError:
        pass
    if rc != 0:
        raise RuntimeError(f"FFmpeg batch merge failed: {stderr[:500]}")


async def speed_adjust(input_path: str, output_path: str, target_duration: float):
    info = await get_video_info(input_path)
    original = info["duration"]
    if abs(original - target_duration) < 0.02:
        import shutil
        shutil.copy2(input_path, output_path)
        return

    factor = original / target_duration
    video_filter = f"setpts={1/factor}*PTS"

    cmd = ["ffmpeg", "-y", "-i", input_path, "-filter:v", video_filter]

    if info["has_audio"]:
        atempo_filters = _build_atempo_chain(factor)
        cmd.extend(["-filter:a", atempo_filters])

    cmd.extend(["-movflags", "+faststart", output_path])
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg speed adjust failed: {stderr[:500]}")


async def normalize_video(input_path: str, output_path: str, target_width: int, target_height: int) -> dict:
    info = await get_video_info(input_path)
    w, h = info["width"], info["height"]

    tw = target_width if target_width % 2 == 0 else target_width + 1
    th = target_height if target_height % 2 == 0 else target_height + 1

    if w == tw and h == th:
        import shutil
        shutil.copy2(input_path, output_path)
        return {"orig_w": w, "orig_h": h, "out_w": tw, "out_h": th}

    scale = min(tw / w, th / h)
    out_w = max(2, int(w * scale) & ~1)
    out_h = max(2, int(h * scale) & ~1)

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"scale={out_w}:{out_h}",
        "-c:a", "copy", "-movflags", "+faststart",
        output_path,
    ]
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg normalize failed: {stderr[:500]}")
    return {"orig_w": w, "orig_h": h, "out_w": out_w, "out_h": out_h}


async def ensure_uniform_encoding(
    input_path: str, output_path: str,
    target_width: Optional[int] = None, target_height: Optional[int] = None,
    target_fps: Optional[float] = None,
    target_duration: Optional[float] = None,
    watermark_path: Optional[str] = None,
    strip_audio: bool = True,
):
    """Re-encode to h264 with uniform resolution/fps/timebase so -c copy concat is safe.

    All operations (scale, pad, fps, strip-audio, trim, watermark) are fused into a
    single FFmpeg invocation to avoid redundant re-encodes downstream.
    When target params are None, probes the input and preserves its own values.

    strip_audio: default True (multi-shot concat workflow requires a uniform no-audio track). When False, keep and re-encode
        the original audio track (native-audio T2V direct-generation), to avoid normalization/watermark re-encoding dropping the sound.
    """
    info = await get_video_info(input_path)
    tw = target_width or info["width"]
    th = target_height or info["height"]
    fps = target_fps or info["fps"]
    tw = tw if tw % 2 == 0 else tw + 1
    th = th if th % 2 == 0 else th + 1
    fps_int = int(round(fps))
    if fps_int <= 0:
        fps_int = 25

    has_watermark = watermark_path and os.path.isfile(watermark_path)
    need_trim = target_duration is not None and target_duration > 0

    dur_ok = (not need_trim) or abs(info.get("duration", 0) - target_duration) < 0.02
    checks = {
        "codec_h264": info.get("codec") == "h264",
        "width_match": info.get("width") == tw,
        "height_match": info.get("height") == th,
        "pix_fmt_yuv420p": info.get("pix_fmt") == "yuv420p",
        "fps_close": abs(info.get("fps", 0) - fps) < 1,
        # strip_audio=True requires no audio track (concat-safe); when keeping audio, an existing audio track does not count as "non-compliant"
        "audio_ok": (not info.get("has_audio", False)) if strip_audio else True,
        "dur_ok": dur_ok,
        "no_watermark": not has_watermark,
    }
    already_ok = all(checks.values())

    in_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    logger.info(
        "uniform_encode CHECK: input=%.2fMB codec=%s %dx%d fps=%.1f dur=%.2f pix_fmt=%s audio=%s | "
        "target=%dx%d %dfps trim=%s wm=%s | already_ok=%s failed=[%s]",
        in_size_mb, info.get("codec"), info.get("width", 0), info.get("height", 0),
        info.get("fps", 0), info.get("duration", 0), info.get("pix_fmt"), info.get("has_audio"),
        tw, th, fps_int,
        f"{target_duration:.2f}s" if need_trim else "no",
        "yes" if has_watermark else "no",
        already_ok,
        ", ".join(k for k, v in checks.items() if not v) or "none",
    )

    timescale = fps_int * 1000
    target_tb = f"1/{timescale}"

    if already_ok:
        if info.get("time_base", "") != target_tb:
            logger.info(
                "uniform_encode REMUX: time_base %s → %s (%.2fMB)",
                info.get("time_base"), target_tb, in_size_mb,
            )
            remux_cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-c", "copy", "-video_track_timescale", str(timescale),
                "-movflags", "+faststart", output_path,
            ]
            rc, _, stderr = await run_ffmpeg(remux_cmd)
            if rc != 0:
                raise RuntimeError(f"FFmpeg remux failed: {stderr[:500]}")
        else:
            import shutil
            shutil.copy2(input_path, output_path)
            logger.info("uniform_encode SKIP (copy only, %.2fMB)", in_size_mb)
        return

    # audio handling: strip_audio=True -> drop the audio track (-an); False and the source has audio -> re-encode to aac and keep
    keep_audio = (not strip_audio) and info.get("has_audio", False)

    if has_watermark:
        logo_size = max(32, int(min(tw, th) * 0.08))
        scale_pad = f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        filter_complex = (
            f"[0:v]{scale_pad}[base];"
            f"[1:v]scale=-1:{logo_size}[logo];"
            f"[base][logo]overlay=W-w-10:H-h-10[outv]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", watermark_path,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
        ]
        if keep_audio:
            cmd += ["-map", "0:a?"]
        cmd += [
            "-c:v", "libx264", "-preset", "ultrafast",
            "-r", str(fps_int), "-video_track_timescale", str(timescale),
        ]
        cmd += (["-c:a", "aac", "-b:a", "192k"] if keep_audio else ["-an"])
        cmd += ["-movflags", "+faststart"]
    else:
        vf = f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast",
            "-r", str(fps_int), "-video_track_timescale", str(timescale),
        ]
        cmd += (["-c:a", "aac", "-b:a", "192k"] if keep_audio else ["-an"])
        cmd += ["-movflags", "+faststart"]

    if need_trim:
        cmd.extend(["-t", f"{target_duration:.3f}"])

    cmd.append(output_path)

    import time as _time
    _t0 = _time.monotonic()
    rc, _, stderr = await run_ffmpeg(cmd)
    _elapsed = _time.monotonic() - _t0
    if rc != 0:
        logger.error("uniform_encode FAIL (%.1fs): %s", _elapsed, stderr[:500])
        raise RuntimeError(f"FFmpeg uniform encode failed: {stderr[:500]}")
    out_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info("uniform_encode OK: %.2fMB → %.2fMB in %.1fs", in_size_mb, out_size_mb, _elapsed)


async def strip_audio(input_path: str, output_path: str):
    cmd = ["ffmpeg", "-y", "-i", input_path, "-an", "-c:v", "copy", "-movflags", "+faststart", output_path]
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg strip audio failed: {stderr[:500]}")


async def mix_audio(video_path: str, audio_path: str, output_path: str, audio_volume: float = 0.3, loop_audio: bool = False):
    info = await get_video_info(video_path)
    audio_input = ["-stream_loop", "-1", "-i", audio_path] if loop_audio else ["-i", audio_path]
    if info["has_audio"]:
        cmd = [
            "ffmpeg", "-y", "-i", video_path, *audio_input,
            "-filter_complex",
            f"[1:a]volume={audio_volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0.1[out]",
            "-map", "0:v", "-map", "[out]",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", video_path, *audio_input,
            "-filter_complex", f"[1:a]volume={audio_volume}[bg]",
            "-map", "0:v", "-map", "[bg]",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            output_path,
        ]
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg mix audio failed: {stderr[:500]}")


async def add_audio_track(video_path: str, audio_path: str, output_path: str):
    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        output_path,
    ]
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg add audio failed: {stderr[:500]}")


def _ffmpeg_stderr_indicates_no_audio_stream(stderr: str) -> bool:
    """When the input has no audio track or it cannot be mapped to the output, FFmpeg commonly errors (not treated as fatal; the caller returns null)."""
    s = (stderr or "").lower()
    # version differences: there is "Output file #0 does ..." or "[out#0/mp3] Output file does ..." (may lack #0)
    if "does not contain any stream" in s and (
        "output file" in s or "out#0" in s or "[out#" in s
    ):
        return True
    if "matches no streams" in s and "0:a" in s:
        return True
    return False


async def extract_audio(video_path: str, output_path: str, audio_format: str = "mp3", quality: str = "192k") -> bool:
    """Extract the audio track from the video into output_path. Returns False if there is no audio track (no valid file written); other failures raise RuntimeError."""
    codec = "libmp3lame" if audio_format == "mp3" else "copy"
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", codec,
        "-ab", quality, "-ar", "44100",
        output_path,
    ]
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        if _ffmpeg_stderr_indicates_no_audio_stream(stderr):
            logger.info(
                "FFmpeg extract_audio: no audio stream in input, skip (path=%s)",
                video_path,
            )
            try:
                if os.path.isfile(output_path):
                    os.unlink(output_path)
            except OSError:
                pass
            return False
        # the first few KB of stderr are mostly version/config banners; the real error is usually at the end
        tail = stderr[-2500:] if stderr and len(stderr) > 2500 else (stderr or "")
        logger.error("FFmpeg extract_audio failed rc=%s stderr_len=%s tail=%s", rc, len(stderr or ""), tail)
        raise RuntimeError(f"FFmpeg extract audio failed (rc={rc}): {tail}")
    return True


async def trim_audio(input_path: str, output_path: str, start: float, duration: float):
    """Clip [start, start+duration), always re-encode.

    ``-c copy`` cuts by packet, and a 15-second request often lands at over 16 seconds, hitting the H3 reference-audio cap.
    Like ``trim_audio_with_fade``, uses libmp3lame to cut precisely to the requested duration by sample point.
    """
    if start < 0.0:
        raise ValueError(f"trim_audio: start must be >= 0, got {start}")
    if duration <= 0.0:
        raise ValueError(f"trim_audio: duration must be > 0, got {duration}")
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{float(start):.3f}",
        "-t", f"{float(duration):.3f}",
        "-i", input_path,
        "-c:a", "libmp3lame", "-q:a", "4",
        output_path,
    ]
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg trim audio failed: {stderr[:500]}")


async def trim_audio_with_fade(
    input_path: str,
    output_path: str,
    start: float,
    duration: float,
    fade_in_sec: float = 0.0,
    fade_out_sec: float = 0.0,
):
    """Trim + fade in/out.

    Difference from ``trim_audio``: uses the ``-af afade`` filter, **cannot** ``-c copy``; uniformly uses libmp3lame
    to re-encode to mp3, avoiding inconsistent fade behavior across container formats.

    The fade-in/out time base is "within the trimmed segment" (0..duration):
        afade=t=in :st=0           :d=fade_in_sec
        afade=t=out:st=duration-fo :d=fade_out_sec
    """
    if duration <= 0.0:
        raise ValueError(f"trim_audio_with_fade: duration must be > 0, got {duration}")
    fi = max(0.0, float(fade_in_sec or 0.0))
    fo = max(0.0, float(fade_out_sec or 0.0))
    # fade should not exceed the segment length
    if fi + fo > duration + 1e-3:
        # do not error directly; scale down proportionally to 80% of the total length, keeping the ffmpeg command valid
        scale = 0.8 * duration / max(fi + fo, 1e-6)
        fi *= scale
        fo *= scale
        logger.warning(
            "trim_audio_with_fade: fade(%.3fs+%.3fs) >= duration(%.3fs)，按比例缩到 (%.3fs+%.3fs)",
            fade_in_sec, fade_out_sec, duration, fi, fo,
        )
    af_parts: list[str] = []
    if fi > 0.0:
        af_parts.append(f"afade=t=in:st=0:d={fi:.3f}")
    if fo > 0.0:
        fo_start = max(0.0, duration - fo)
        af_parts.append(f"afade=t=out:st={fo_start:.3f}:d={fo:.3f}")

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{float(start):.3f}",
        "-t", f"{float(duration):.3f}",
        "-i", input_path,
    ]
    if af_parts:
        cmd.extend(["-af", ",".join(af_parts)])
    # output uniformly as mp3 (consistent with existing trim_audio_with_fade callers); libmp3lame -q:a 4 ~ 128~165kbps VBR
    cmd.extend(["-c:a", "libmp3lame", "-q:a", "4", output_path])

    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg trim+fade audio failed: {stderr[:500]}")


async def extract_audio_peaks(
    input_path: str,
    sample_count: int = 512,
) -> tuple[float, list[float]]:
    """Extract a normalized audio peak array (for the frontend canvas waveform).

    Flow:
    1) use ffmpeg to decode to mono 8kHz s16le PCM output to stdout
    2) numpy bucketing, take max(abs) per bucket
    3) normalize to [0, 1]

    Returns:
        (duration_sec, values[sample_count])
    """
    if sample_count <= 0:
        raise ValueError(f"sample_count must be > 0, got {sample_count}")
    # 1) decode
    cmd = [
        "ffmpeg", "-v", "error", "-i", input_path,
        "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.request_timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("FFmpeg extract_audio_peaks timeout")
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg extract_audio_peaks failed: {stderr.decode()[:500]}")

    if not stdout:
        return 0.0, [0.0] * sample_count

    # 2) numpy bucketing; s16le is 2 bytes per sample
    import numpy as np
    pcm = np.frombuffer(stdout, dtype=np.int16)
    if pcm.size == 0:
        return 0.0, [0.0] * sample_count
    duration_sec = pcm.size / 8000.0
    # split into sample_count buckets
    bucket_size = max(1, pcm.size // sample_count)
    # cap the pcm length to an integer multiple of sample_count*bucket_size, discarding a tiny bit of the tail
    usable = bucket_size * sample_count
    pcm_trim = pcm[:usable]
    buckets = pcm_trim.reshape(sample_count, bucket_size)
    peaks = np.abs(buckets).max(axis=1).astype(np.float32)
    max_peak = float(peaks.max()) if peaks.size > 0 else 0.0
    if max_peak <= 0.0:
        return duration_sec, [0.0] * sample_count
    norm = (peaks / max_peak).tolist()
    return duration_sec, [float(round(v, 4)) for v in norm]


async def convert_audio(input_path: str, output_path: str):
    cmd = ["ffmpeg", "-y", "-i", input_path, output_path]
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg convert audio failed: {stderr[:500]}")


async def create_placeholder(output_path: str, duration: float, width: int, height: int, fps: int):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={fps}:d={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-movflags", "+faststart",
        output_path,
    ]
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0:
        raise RuntimeError(f"FFmpeg placeholder failed: {stderr[:500]}")


def _input_seek_sec(timestamp: float) -> float:
    """Format ffmpeg ``-ss`` without rounding up past the last frame PTS.

    ``9.916667`` rounded to 3 decimals is ``9.917``, which seeks past EOF.
    Flooring to milliseconds keeps the last decodable frame.
    """
    return math.floor(max(0.0, float(timestamp)) * 1000.0) / 1000.0


async def extract_frame(
    input_path: str,
    output_path: str,
    timestamp: Optional[float],
    *,
    position: str = "timestamp",
    image_format: str = "jpeg",
) -> dict:
    """Grab a single still frame at ``timestamp`` seconds from a video.

    Uses input seeking (``-ss`` before ``-i``) for speed; clamps negative
    timestamps to 0. A timestamp at or past the last decoded frame is
    floored to that frame (container duration is often one frame later,
    and millisecond rounding can skip the last PTS).
    """
    normalized_position = (position or "timestamp").strip().lower()
    if normalized_position not in {"timestamp", "last"}:
        raise ValueError("position must be 'timestamp' or 'last'")
    last_t = await _last_video_frame_timestamp(input_path)
    if normalized_position == "last":
        t = last_t
    else:
        t = max(0.0, min(float(timestamp or 0.0), last_t))
    t = _input_seek_sec(t)
    fmt = (image_format or "jpeg").strip().lower()
    if fmt in {"jpg", "jpeg"}:
        fmt = "jpeg"
        quality_args = ["-q:v", "2"]
    elif fmt == "png":
        quality_args = []
    else:
        raise ValueError(f"unsupported frame image format: {image_format}")

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{t:.3f}",
        "-i",
        input_path,
        "-frames:v",
        "1",
        *quality_args,
        output_path,
    ]
    rc, _, stderr = await run_ffmpeg(cmd)
    if rc != 0 or not os.path.isfile(output_path):
        raise RuntimeError(f"FFmpeg extract_frame failed: {stderr[:500]}")

    width = height = None
    try:
        data = await ffprobe_json(output_path)
        stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            None,
        )
        if stream:
            width = int(stream.get("width") or 0) or None
            height = int(stream.get("height") or 0) or None
    except Exception as exc:  # noqa: BLE001 — probe is best-effort
        logger.warning("extract_frame probe failed: %s", exc)

    return {
        "timestamp": t,
        "position": normalized_position,
        "format": fmt,
        "width": width,
        "height": height,
    }


async def _last_video_frame_timestamp(input_path: str) -> float:
    """Return the PTS of the final decoded video frame, ignoring a longer audio tail."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "frame=best_effort_timestamp_time",
        "-of",
        "csv=p=0",
        input_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe final-frame lookup failed: {stderr.decode()[:500]}")
    for raw in reversed(stdout.decode().splitlines()):
        value = raw.strip().split(",", 1)[0]
        if not value or value == "N/A":
            continue
        try:
            return max(0.0, float(value))
        except ValueError:
            continue
    raise RuntimeError("No decoded video frame timestamp found")


def _pick_reference_params(infos: list[dict]) -> tuple[int, int, float]:
    """Pick reference resolution and fps from a list of video infos.
    Uses the video with the lowest fps as reference (avoids dropped frames).
    Returns (width, height, fps) with even dimensions."""
    valid = [i for i in infos if i.get("fps", 0) > 0]
    if not valid:
        return 1280, 720, 25.0
    ref = min(valid, key=lambda i: i["fps"])
    tw = ref["width"] if ref["width"] % 2 == 0 else ref["width"] + 1
    th = ref["height"] if ref["height"] % 2 == 0 else ref["height"] + 1
    fps = ref["fps"] if ref["fps"] > 0 else 25.0
    logger.info(
        "reference video: %dx%d fps=%.2f (selected min fps from %d videos, fps range %.2f-%.2f)",
        tw, th, fps, len(valid),
        min(i["fps"] for i in valid), max(i["fps"] for i in valid),
    )
    return tw, th, fps


def _parse_fps(fps_str: str) -> float:
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            return round(float(num) / float(den), 2)
        return float(fps_str)
    except (ValueError, ZeroDivisionError):
        return 25.0


def _build_atempo_chain(factor: float) -> str:
    parts = []
    remaining = factor
    if factor > 2.0:
        while remaining > 2.0:
            parts.append("atempo=2.0")
            remaining /= 2.0
        if remaining > 1.001:
            parts.append(f"atempo={remaining:.4f}")
    elif factor < 0.5:
        while remaining < 0.5:
            parts.append("atempo=0.5")
            remaining /= 0.5
        if remaining < 0.999:
            parts.append(f"atempo={remaining:.4f}")
    else:
        parts.append(f"atempo={factor:.4f}")
    return ",".join(parts) if parts else f"atempo={factor:.4f}"
