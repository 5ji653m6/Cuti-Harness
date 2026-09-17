"""
Audio-transcription tool module
Provides advanced audio transcription, including download-from-S3 and transcription
"""

import logging
import tempfile
import base64
import bisect
import subprocess
import json
import os
import asyncio
from pathlib import Path
from typing import Optional, List, Union, Dict, Any, Tuple
from pydantic import BaseModel, Field
import aiofiles

from app.utils.s3_utils import s3_utils
from app.utils import media_service_client as msc
from app.models.video_state import AudioTranscription, AudioSegment
from app.models.user_options import UserOption
from app.models.tool_enums import AudioSegmentGranularity, DefaultValues

logger = logging.getLogger(__name__)


def should_apply_lipsync_constraint(
    user_option: Optional[UserOption],
    *,
    music_intent: Optional[str] = None,
    music_workflow_mode: Optional[str] = None,
) -> bool:
    """Whether to apply a lipsync duration constraint to the audio segment."""
    from app.models.user_options import should_enable_lipsync_for_run

    return should_enable_lipsync_for_run(
        user_option,
        music_intent=music_intent,
        music_workflow_mode=music_workflow_mode,
    )


def get_lipsync_max_segment_duration(user_option: Optional[UserOption]) -> int:
    """Max segment duration (seconds) in lipsync mode, matching the discrete upper bound of audio-driven planning."""
    from app.agent_config.duration import get_audio_driven_duration_values

    return max(get_audio_driven_duration_values(user_option) or [15])


def _resolve_granularity(
    explicit: Optional[AudioSegmentGranularity],
) -> AudioSegmentGranularity:
    """Resolve the split granularity uniformly: explicit argument > DefaultValues fallback.

    granularity is not attached to UserOption -- it is a transcribe **engine config**,
    at the same level as `DefaultValues.TRANSCRIPTION_METHOD`; the caller
    (music_generation_service) resolves it via `TRANSCRIPTION_METHOD_CONFIG[method]["granularity"]`
    and passes it in explicitly; this function only handles "fallback when the argument is missing".
    """
    if explicit is not None:
        return AudioSegmentGranularity.from_value(explicit)
    return AudioSegmentGranularity.from_value(DefaultValues.AUDIO_SEGMENT_GRANULARITY)


def parse_time_to_seconds(time_str: str) -> float:
    """
    Convert a time string to seconds. transcribe output is uniformly MM:SS.mmm format.

    Supported formats:
    - MM:SS.mmm (e.g. "1:20.500" -> 80.5, "0:12.250" -> 12.25)
    - MM:SS, MM:SS.SS (for compatibility)
    - plain seconds (e.g. "80.5")
    """
    try:
        time_str = time_str.strip()
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 2:
                minutes = float(parts[0])
                seconds = float(parts[1])
                return minutes * 60 + seconds
            logger.warning(f"无法解析时间格式: {time_str}")
            return 0.0
        return float(time_str)
    except (ValueError, IndexError) as e:
        logger.error(f"时间格式解析失败: {time_str}, 错误: {e}")
        return 0.0


# ==================== Gemini audio-transcription structured-output models ====================
class GeminiAudioWord(BaseModel):
    """Gemini audio-transcription word (word-level timestamps, MM:SS.mmm format)."""
    id: int = Field(description="词汇ID（序号）")
    word: str = Field(description="词汇文本")
    start: str = Field(description="开始时间（MM:SS.mmm 格式，如 0:12.250）")
    end: str = Field(description="结束时间（MM:SS.mmm 格式，如 0:12.850）")

class GeminiAudioSegment(BaseModel):
    """Gemini audio-transcription segment. Time fields are all MM:SS.mmm format (min:sec.millis, e.g. 0:12.250, 1:20.500)."""
    id: int = Field(description="片段ID（序号）")
    start: str = Field(description="开始时间（MM:SS.mmm 格式，如 0:12.250）")
    end: str = Field(description="结束时间（MM:SS.mmm 格式，如 1:20.500）")
    text: str = Field(description="转录文本或音乐段落描述")
    duration: str = Field(description="片段时长（MM:SS.mmm 格式，如 0:05.300）")
    emotion: Optional[str] = Field(default=None, description="情感/调性")
    tempo: Optional[str] = Field(default=None, description="速度/动态")
    vocal_presence: Optional[bool] = Field(default=None, description="是否有人声/演唱，用于 lipsync 是否张嘴")
    vocal_gender: Optional[str] = Field(default=None, description="人声性别：'f' 女声，'m' 男声；仅能听辨时填，否则不填")
    section_index: Optional[int] = Field(default=None, description="所属段落在 sections 中的下标，用于与曲式对齐")


class GeminiSection(BaseModel):
    """Gemini song structure section; times are all MM:SS.mmm format."""
    section_type: str = Field(description="段落类型，如 Intro, Verse 1, Chorus 1, Bridge, Outro")
    start_seconds: str = Field(description="开始时间（MM:SS.mmm 格式，如 0:00.000）")
    end_seconds: str = Field(description="结束时间（MM:SS.mmm 格式，如 0:32.500）")
    musical_features: Optional[str] = Field(default=None, description="该段音乐特征描述")
    section_emotion: Optional[str] = Field(default=None, description="该段情绪")
    suggested_visual_intensity: Optional[str] = Field(default=None, description="建议视觉强度")
    suggested_rhythmic_strategy: Optional[str] = Field(default=None, description="建议节奏策略")
    suggested_visual_theme: Optional[str] = Field(default=None, description="建议视觉主题")
    suggested_context: Optional[str] = Field(default=None, description="建议场景/上下文")


class GeminiTranscriptionResult(BaseModel):
    """Gemini audio-transcription result (with whole-track Global, sections, and segments). Whole-track duration is MM:SS.mmm format."""
    task: str = Field(description="任务类型", default="transcribe")
    language: str = Field(description="识别语言")
    duration: str = Field(description="总时长（MM:SS.mmm 格式，如 2:05.120）")
    text: str = Field(description="完整转录文本或音乐整体描述")
    is_instrumental: bool = Field(description="是否为纯音乐（无歌词）")
    # Whole-track Global (maps to the video_audio_transcription table)
    song_name: Optional[str] = Field(default=None, description="歌曲名称")
    global_bpm: Optional[Union[int, float]] = Field(default=None, description="整曲 BPM")
    genre: Optional[str] = Field(default=None, description="音乐流派")
    global_emotion: Optional[str] = Field(default=None, description="整曲听觉情绪/基调")
    suggested_global_theme: Optional[str] = Field(default=None, description="建议核心设计理念")
    suggested_color_palette: Optional[str] = Field(default=None, description="建议整体色彩倾向")
    segments: List[GeminiAudioSegment] = Field(description="音频片段列表，每段含 emotion/tempo")
    sections: List[GeminiSection] = Field(default_factory=list, description="Song Structure 段落列表，须输出")


# Merge empty-text segments into the previous one: duration < this threshold (seconds)
SHORT_EMPTY_MERGE_THRESHOLD_SEC = 5.0


def prune_sections_without_segment_overlap(
    sections: List[Dict[str, Any]],
    segments: List[AudioSegment],
) -> List[Dict[str, Any]]:
    """Delete song-structure sections that do not overlap any segment in time (drop empty windows after merge, no placeholder kept)."""
    if not sections:
        return sections
    kept: List[Dict[str, Any]] = []
    for sec in sorted(sections, key=lambda s: float(s.get("start_time") or 0)):
        st = float(sec.get("start_time") or 0)
        et = float(sec.get("end_time") or 0)
        if et <= st:
            logger.info(
                "🗑️ 删除无效曲式段落（end<=start）: %s [%.3f-%.3f]",
                sec.get("section_type", "?"),
                st,
                et,
            )
            continue
        has_overlap = any(
            float(seg.start) < et - 1e-9 and float(seg.end) > st + 1e-9
            for seg in segments
        )
        if has_overlap:
            kept.append(sec)
        else:
            logger.info(
                "🗑️ 删除无 segment 重叠的曲式段落: %s [%.3f-%.3f]",
                sec.get("section_type", "?"),
                st,
                et,
            )
    return kept


def merge_short_empty_segments(
    segments: List[AudioSegment],
    duration_threshold: float = SHORT_EMPTY_MERGE_THRESHOLD_SEC,
) -> List[AudioSegment]:
    """
    Merge short empty-text segments into the previous segment.

    In audio-driven mode, Whisper word-level transcription + LLM caption assembly produce many short pauses (0.5-1.5s).
    fill_gaps treats these short pauses as standalone empty-text segments, causing too many scene changes.

    Strategy: merge short empty-text segments (empty text and duration < threshold) into the previous segment.

    Why merge into the previous rather than the next?
    1. Visual continuity: short pauses are usually breaths/rhythm pauses between lyrics and should extend the previous segment's visuals.
    2. Natural transition: a scene fades out naturally after the lyrics end, rather than opening on silence.
    3. Matches music-video rhythm: action/performance happens during lyrics; pauses are the afterglow/freeze.
    4. More natural LLM scene descriptions: "sing XX, then pause and look into the distance" vs "pause, then start singing XX".

    Args:
        segments: list of audio segments (already sorted by start)
        duration_threshold: duration threshold (seconds); empty-text segments shorter than this are merged into the previous one

    Returns:
        the merged list of audio segments

    Notes:
        - Only merge empty-text segments that have a preceding segment (the first segment is not merged)
        - Preserve time continuity; update the merged segment's end and duration
    """
    if not segments:
        return segments

    merged_segments = []
    sorted_segments = sorted(segments, key=lambda s: s.start)

    for i, segment in enumerate(sorted_segments):
        # Determine whether this is a short empty-text segment
        is_short_empty = (not segment.text.strip()) and (segment.duration < duration_threshold)

        # If it is a short empty-text segment and there is a previous segment, merge into it
        if is_short_empty and merged_segments:
            prev_segment = merged_segments[-1]
            # Extend the previous segment's end time
            merged_segment = AudioSegment(
                id=prev_segment.id,
                start=prev_segment.start,
                end=segment.end,  # extend to the current segment's end time
                text=prev_segment.text,  # keep the previous segment's text
                duration=segment.end - prev_segment.start,  # update duration
                emotion=prev_segment.emotion,  # keep the previous segment's emotion
                tempo=prev_segment.tempo,  # keep the previous segment's tempo
                vocal_presence=getattr(prev_segment, "vocal_presence", None),
                vocal_gender=getattr(prev_segment, "vocal_gender", None),
            )
            merged_segments[-1] = merged_segment  # replace the previous segment
            logger.info(f"📝 合并短时空文本片段 {segment.id} ({segment.duration:.2f}s) 到前一个片段 {prev_segment.id}")
        else:
            # Add the segment normally
            merged_segments.append(segment)

    # Reassign ids
    for i, segment in enumerate(merged_segments):
        segment.id = i

    return merged_segments


# Merge any too-short segment into an adjacent one: duration < this threshold (seconds); runs after section splitting + empty-segment merge
MICRO_SEGMENT_MIN_DURATION_SEC = 3.0


def merge_micro_duration_segments(
    segments: List[AudioSegment],
    min_duration: float = MICRO_SEGMENT_MIN_DURATION_SEC,
) -> List[AudioSegment]:
    """
    Merge over-short segments (interlude fragments, sub-second model junk, 1ms fragments from section splitting, etc.).

    - Prefer merging into the **previous** segment (extend end), consistent with merge_short_empty_segments.
    - If there is no previous segment, merge into the **next** one (extend start).

    May run multiple rounds until no sub-threshold segments remain.
    """
    if not segments:
        return segments
    segs: List[AudioSegment] = list(segments)
    while True:
        segs.sort(key=lambda s: float(s.start))
        merged: List[AudioSegment] = []
        i = 0
        made_change = False
        while i < len(segs):
            seg = segs[i]
            d = max(0.0, float(seg.end) - float(seg.start))
            if d + 1e-9 >= min_duration:
                merged.append(seg)
                i += 1
                continue
            if merged:
                prev = merged[-1]
                made_change = True
                _text_parts = [p for p in [(prev.text or "").strip(), (seg.text or "").strip()] if p]
                merged[-1] = AudioSegment(
                    id=prev.id,
                    start=float(prev.start),
                    end=float(seg.end),
                    text=" ".join(_text_parts),
                    duration=float(seg.end) - float(prev.start),
                    emotion=prev.emotion,
                    tempo=prev.tempo,
                    vocal_presence=getattr(prev, "vocal_presence", None),
                    vocal_gender=getattr(prev, "vocal_gender", None),
                )
                logger.info(
                    "📝 合并过短切片 %.4fs 入上一段 → [%.3f, %.3f]",
                    d,
                    float(prev.start),
                    float(seg.end),
                )
                i += 1
            elif i + 1 < len(segs):
                made_change = True
                nxt = segs[i + 1]
                _text_parts = [p for p in [(seg.text or "").strip(), (nxt.text or "").strip()] if p]
                segs[i + 1] = AudioSegment(
                    id=0,
                    start=float(seg.start),
                    end=float(nxt.end),
                    text=" ".join(_text_parts),
                    duration=float(nxt.end) - float(seg.start),
                    emotion=nxt.emotion,
                    tempo=nxt.tempo,
                    vocal_presence=getattr(nxt, "vocal_presence", None),
                    vocal_gender=getattr(nxt, "vocal_gender", None),
                )
                logger.info(
                    "📝 合并过短片头 %.4fs 入下一段 → [%.3f, %.3f]",
                    d,
                    float(seg.start),
                    float(nxt.end),
                )
                i += 1
            else:
                merged.append(seg)
                i += 1
        for j, s in enumerate(merged):
            s.id = j
        segs = merged
        if not made_change:
            break
    return segs


def snap_segment_edges_to_bar_grid(
    segments: List[AudioSegment],
    bar_dur_sec: float,
    tolerance_sec: float = 0.20,
    word_edges_sec: Optional[List[float]] = None,
    total_duration: Optional[float] = None,
) -> List[AudioSegment]:
    """**Beat-mode** post-processing: snap segment endpoints to 4/4 bar lines (t_n = bar_dur x n).

    Design points:
      - Only snap when |edge - nearest_bar| <= tolerance; otherwise leave it (avoid disturbing the LLM's reasonable cut points)
      - **Lyric protection**: if a snap point lands inside a word (`word_edges_sec`), drift to the nearest word boundary;
        when `word_edges_sec` is empty (pure instrumental / no words provided), this protection does not trigger
      - Strictly keep adjacent segment endpoints continuous: seg[i].end == seg[i+1].start
      - Do not change sections; do not add or remove segments, only adjust start/end
      - First segment start >= 0; last segment end <= total_duration (if provided)

    Compatible with `merge_micro_duration_segments`: if snapping produces segments < the MICRO threshold,
    the caller may run micro-merge again (this function does not merge on its own to keep side effects minimal).
    """
    if not segments or bar_dur_sec <= 0:
        return list(segments)

    edges_sorted = sorted(set(float(x) for x in (word_edges_sec or []) if x is not None))

    def _is_inside_word(t: float) -> bool:
        if not edges_sorted:
            return False
        idx = bisect.bisect_right(edges_sorted, t)
        if idx <= 0 or idx >= len(edges_sorted):
            return False
        return (t - edges_sorted[idx - 1] > 1e-3) and (edges_sorted[idx] - t > 1e-3)

    def _nearest_word_edge(t: float) -> Optional[float]:
        if not edges_sorted:
            return None
        idx = bisect.bisect_left(edges_sorted, t)
        candidates = []
        if idx < len(edges_sorted):
            candidates.append(edges_sorted[idx])
        if idx > 0:
            candidates.append(edges_sorted[idx - 1])
        return min(candidates, key=lambda x: abs(x - t)) if candidates else None

    def _snap(t: float) -> float:
        if t < 0:
            return 0.0
        n = round(t / bar_dur_sec)
        snapped = n * bar_dur_sec
        if abs(snapped - t) > tolerance_sec:
            return t
        if _is_inside_word(snapped):
            nearest = _nearest_word_edge(snapped)
            if nearest is not None and abs(nearest - snapped) <= tolerance_sec:
                return nearest
            return t
        return snapped

    sorted_segs = sorted(segments, key=lambda s: float(s.start))
    new_starts: List[float] = []
    for i, seg in enumerate(sorted_segs):
        if i == 0:
            new_starts.append(0.0 if float(seg.start) <= 1e-3 else _snap(float(seg.start)))
        else:
            new_starts.append(_snap(float(seg.start)))

    out: List[AudioSegment] = []
    n = len(sorted_segs)
    for i, seg in enumerate(sorted_segs):
        s_new = new_starts[i]
        if i + 1 < n:
            e_new = new_starts[i + 1]
        else:
            e_new = _snap(float(seg.end))
            if total_duration is not None and e_new > float(total_duration):
                e_new = float(total_duration)
        if e_new <= s_new:
            e_new = float(seg.end)
            s_new = min(s_new, e_new - 1e-3)
        out.append(AudioSegment(
            id=i,
            start=s_new,
            end=e_new,
            text=seg.text,
            duration=e_new - s_new,
            emotion=seg.emotion,
            tempo=seg.tempo,
            vocal_presence=getattr(seg, "vocal_presence", None),
            vocal_gender=getattr(seg, "vocal_gender", None),
        ))
    return out


async def get_audio_duration(audio_url: str) -> Optional[float]:
    """Get the audio file duration."""
    result = await msc.audio_info(audio_url)
    duration = result.get("duration")
    if duration is not None:
        logger.info(f"✅ Media service audio_info duration: {duration}")
        return float(duration)
    return None


def fill_gaps_in_segments(segments: List[AudioSegment], total_duration: float, gap_threshold: float = 0.1) -> List[AudioSegment]:
    """
    Fill in the missing time gaps between audio segments.

    Args:
        segments: original list of audio segments (already sorted by start)
        total_duration: total audio duration
        gap_threshold: gap threshold (seconds); only gaps larger than this are filled

    Returns:
        the gap-filled list of audio segments
    """
    if not segments:
        return segments

    filled_segments = []
    sorted_segments = sorted(segments, key=lambda s: s.start)
    segment_id_counter = 0

    # Check for a gap at the start
    if sorted_segments[0].start > gap_threshold:
        gap_segment = AudioSegment(
            id=segment_id_counter,
            start=0.0,
            end=sorted_segments[0].start,
            text="",  # gap segments use empty text
            duration=sorted_segments[0].start,
            emotion=None,  # gap segments have no emotion
            tempo=None  # gap segments have no tempo
        )
        filled_segments.append(gap_segment)
        segment_id_counter += 1
        logger.info(f"📝 填补开头缺失片段: 0.0s - {sorted_segments[0].start:.2f}s")

    # Keep existing segments and check for gaps in between
    for i, segment in enumerate(sorted_segments):
        # Create a new segment, update id
        filled_segment = AudioSegment(
            id=segment_id_counter,
            start=segment.start,
            end=segment.end,
            text=segment.text,
            duration=segment.duration,
            emotion=segment.emotion,  # keep the original emotion
            tempo=segment.tempo,  # keep the original tempo
            vocal_presence=getattr(segment, "vocal_presence", None),
            vocal_gender=getattr(segment, "vocal_gender", None),
        )
        filled_segments.append(filled_segment)
        segment_id_counter += 1

        # Check the gap to the next segment
        if i < len(sorted_segments) - 1:
            next_segment = sorted_segments[i + 1]
            gap = next_segment.start - segment.end
            if gap > gap_threshold:
                gap_segment = AudioSegment(
                    id=segment_id_counter,
                    start=segment.end,
                    end=next_segment.start,
                    text="",  # gap segments use empty text
                    duration=gap,
                    emotion=None,  # gap segments have no emotion
                    tempo=None  # gap segments have no tempo
                )
                filled_segments.append(gap_segment)
                segment_id_counter += 1
                logger.info(f"📝 填补中间缺失片段: {segment.end:.2f}s - {next_segment.start:.2f}s")

    # Check for a gap at the end
    if sorted_segments:
        last_segment = sorted_segments[-1]
        if last_segment.end < total_duration - gap_threshold:
            gap_segment = AudioSegment(
                id=segment_id_counter,
                start=last_segment.end,
                end=total_duration,
                text="",  # gap segments use empty text
                duration=total_duration - last_segment.end,
                emotion=None,  # gap segments have no emotion
                tempo=None  # gap segments have no tempo
            )
            filled_segments.append(gap_segment)
            logger.info(f"📝 填补结尾缺失片段: {last_segment.end:.2f}s - {total_duration:.2f}s")

    return filled_segments


def merge_leading_gap_fill_into_next(
    segments: List[AudioSegment],
    *,
    max_gap_duration: float = SHORT_EMPTY_MERGE_THRESHOLD_SEC,
) -> List[AudioSegment]:
    """Merge the leading empty segment produced by fill_gaps (0 -> first-line start) into the next one, avoiding a leftover ~0.48s junk segment.

    Unlike the trailing Outro of a song boundary: the leading gap's start is 0 and should belong to the same segment as the first lyric line."""
    if len(segments) < 2:
        return segments
    sorted_segs = sorted(segments, key=lambda s: float(s.start))
    head, nxt = sorted_segs[0], sorted_segs[1]
    head_d = float(head.end) - float(head.start)
    if (
        float(head.start) > 0.05
        or (head.text or "").strip()
        or head_d <= 0
        or head_d >= max_gap_duration
    ):
        return segments
    merged = AudioSegment(
        id=nxt.id,
        start=0.0,
        end=float(nxt.end),
        text=nxt.text,
        duration=float(nxt.end),
        emotion=nxt.emotion,
        tempo=nxt.tempo,
        vocal_presence=getattr(nxt, "vocal_presence", None),
        vocal_gender=getattr(nxt, "vocal_gender", None),
    )
    rest = sorted_segs[2:]
    out = [merged] + rest
    for i, s in enumerate(out):
        s.id = i
    logger.info(
        "📝 片头填补空隙 %.3fs 并入下一段 → [0.000, %.3f]",
        head_d,
        float(nxt.end),
    )
    return out


def postprocess_transcription_segments(
    segments: List[AudioSegment],
    *,
    total_duration: float = 0.0,
    sections_for_split: Optional[List[dict]] = None,
    fill_gaps_enabled: bool = True,
) -> List[AudioSegment]:
    """Unified post-processing of transcription segments (shared by hybrid / Gemini-only).

    Order (cross-section splitting must happen first, then trim tails afterward):
      1. fill_gaps - fill timeline holes
      1b. merge_leading_gap_fill - merge the leading 0->first-line empty segment into the next one
      2. split_at_section_boundaries - always split across song-structure boundaries
      3. merge_short_empty - merge empty-text and < 5s into the previous segment
      4. merge_micro - merge any < 3s into an adjacent segment
    """
    if not segments:
        return segments
    out = list(segments)
    if fill_gaps_enabled and total_duration > 0:
        n0 = len(out)
        out = fill_gaps_in_segments(out, total_duration)
        if len(out) != n0:
            logger.info("📝 填补时间段完成: %d -> %d 个片段", n0, len(out))
    n_lead = len(out)
    out = merge_leading_gap_fill_into_next(out)
    if len(out) != n_lead:
        logger.info("📝 片头空隙并入下一段: %d -> %d 个片段", n_lead, len(out))
    if sections_for_split:
        n1 = len(out)
        out = split_segments_at_section_boundaries(out, sections_for_split)
        if len(out) != n1:
            logger.info("✂️ section 边界对齐完成: %d -> %d 个片段", n1, len(out))
    n2 = len(out)
    out = merge_short_empty_segments(
        out,
        duration_threshold=SHORT_EMPTY_MERGE_THRESHOLD_SEC,
    )
    if len(out) != n2:
        logger.info("📝 合并短时空文本片段完成: %d -> %d 个片段", n2, len(out))
    n3 = len(out)
    out = merge_micro_duration_segments(
        out,
        min_duration=MICRO_SEGMENT_MIN_DURATION_SEC,
    )
    if len(out) != n3:
        logger.info(
            "📝 合并过短切片完成: %d -> %d 个片段（阈值=%ss）",
            n3,
            len(out),
            MICRO_SEGMENT_MIN_DURATION_SEC,
        )
    return out


def postprocess_transcription(
    segments: List[AudioSegment],
    sections: Optional[List[Dict[str, Any]]] = None,
    *,
    total_duration: float = 0.0,
    fill_gaps_enabled: bool = True,
) -> Tuple[List[AudioSegment], List[Dict[str, Any]]]:
    """Post-process segments + trim song-structure sections to the final segment timeline (delete if no overlap)."""
    secs = list(sections or [])
    split_input = (
        [{"start_time": float(s["start_time"]), "end_time": float(s["end_time"])} for s in secs]
        if secs
        else None
    )
    out_segs = postprocess_transcription_segments(
        segments,
        total_duration=total_duration,
        sections_for_split=split_input,
        fill_gaps_enabled=fill_gaps_enabled,
    )
    if secs:
        n_sec = len(secs)
        secs = prune_sections_without_segment_overlap(secs, out_segs)
        if len(secs) != n_sec:
            logger.info("🎵 曲式修剪完成: %d -> %d 个段落", n_sec, len(secs))
        _sync_section_end_times_to_segments(secs, out_segs, total_duration)
    return out_segs, secs


def _sync_section_end_times_to_segments(
    sections_list: List[Dict[str, Any]],
    audio_segments: List[AudioSegment],
    actual_duration: float,
) -> None:
    """Gemini's raw song-structure end_time may be shorter than the timeline after fill_gaps/splitting; pull the "last section sorted by start_time"
    end_time up to at least max(actual_duration, max(seg.end)), consistent with the persisted video_audio_segment."""
    if not sections_list:
        return
    timeline_end = float(actual_duration)
    if audio_segments:
        timeline_end = max(timeline_end, max(float(s.end) for s in audio_segments))
    ordered = sorted(
        sections_list,
        key=lambda s: float(s.get("start_time") or 0),
    )
    last_sec = ordered[-1]
    old_et = float(last_sec.get("end_time") or 0)
    new_et = max(old_et, timeline_end)
    if new_et > old_et:
        last_sec["end_time"] = new_et
        logger.info(
            "🎵 曲式最后一节 end_time 已与最终切片对齐: %.3fs -> %.3fs",
            old_et,
            new_et,
        )


def fallback_full_track_sections(
    actual_duration: float,
    audio_segments: List[AudioSegment],
    *,
    global_emotion: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """When Gemini returns no song structure: a single section covers the whole track, for additional_data / video_audio_section."""
    end_bound = float(actual_duration)
    if audio_segments:
        end_bound = max(end_bound, max(float(s.end) for s in audio_segments))
    return [
        {
            "section_type": "整曲",
            "start_time": 0.0,
            "end_time": end_bound,
            "musical_features": None,
            "section_emotion": global_emotion,
            "suggested_visual_intensity": None,
            "suggested_rhythmic_strategy": None,
            "suggested_visual_theme": None,
            "suggested_context": "模型未返回曲式段落，系统默认整轨一段。",
        }
    ]


def split_segments_at_section_boundaries(
    segments: List[AudioSegment],
    sections: List[dict],
) -> List[AudioSegment]:
    """
    Split segments that cross section boundaries so each segment belongs to exactly one section.
    A post-processing step at the same level as fill_gaps / merge_short_empty_segments.

    When a segment [start, end] crosses a section boundary point, split it into two sub-segments at that boundary;
    the lyrics (text) go to the first part, the following sub-segment's text is empty, and emotion/tempo/vocal_presence are inherited from the original segment.

    Args:
        segments: list of audio segments (already sorted by start)
        sections: list of sections, each dict containing start_time / end_time (seconds)

    Returns:
        the split list of audio segments (sorted by start, ids renumbered)
    """
    if not sections or not segments:
        return segments

    boundaries = sorted(set(
        [float(s["start_time"]) for s in sections] + [float(s["end_time"]) for s in sections]
    ))

    result: List[AudioSegment] = []
    for seg in segments:
        split_points = [b for b in boundaries if seg.start + 0.05 < b < seg.end - 0.05]

        if not split_points:
            result.append(seg)
            continue

        all_points = [seg.start] + split_points + [seg.end]
        for i in range(len(all_points) - 1):
            sub_start = round(all_points[i], 3)
            sub_end = round(all_points[i + 1], 3)
            result.append(AudioSegment(
                id=0,
                start=sub_start,
                end=sub_end,
                text=seg.text if i == 0 else "",
                duration=round(sub_end - sub_start, 3),
                emotion=seg.emotion,
                tempo=seg.tempo,
                vocal_presence=getattr(seg, "vocal_presence", None),
            ))
            if i == 0 and seg.text:
                logger.info(
                    f"✂️ segment 跨 section 边界拆分: [{seg.start:.2f}-{seg.end:.2f}] "
                    f"→ [{sub_start:.2f}-{sub_end:.2f}] (text) + 后续 {len(split_points)} 段"
                )

    for i, s in enumerate(result):
        s.id = i
    return result


async def transcribe_audio_with_gemini(
    audio_url: str,
    user_option: Optional[UserOption] = None,
    fill_gaps: bool = True,
    user_input: Optional[str] = None,
    filename: Optional[str] = None,
    generated_lyrics: Optional[str] = None,
    suno_alignment_context: Optional[str] = None,
    granularity: Optional[AudioSegmentGranularity] = None,
    music_intent: Optional[str] = None,
    music_workflow_mode: Optional[str] = None,
    language_contract: Optional[Dict[str, Any]] = None,
) -> Optional[AudioTranscription]:
    """
    Transcribe an audio file using Gemini.

    Args:
        audio_url: CDN URL of the audio file
        user_option: user-option configuration (parameter kept for now, but no longer used to merge segments)
        fill_gaps: whether to fill missing time gaps (default True)
        user_input: user-provided content (may include lyrics), used to correct recognition results
        filename: original audio file name
        generated_lyrics: lyrics from AI music generation (highest accuracy, when the song was Suno-generated)

    Returns:
        Optional[AudioTranscription]: transcription result, None on failure

    Notes:
        - Uses the Gemini 2.5 Flash model for audio transcription
        - Supports multiple audio formats
        - Returns a format consistent with Whisper transcription
        - Lyric-reference accuracy: generated_lyrics > user_input > auto recognition
    """
    try:
        logger.info(f"🎵 开始使用 Gemini 转录音频文件: {audio_url}")

        # Get the file extension from the URL
        ext = Path(audio_url).suffix
        if not ext:
            ext = '.mp3'  # default audio extension

        # Determine the MIME type
        mime_type_map = {
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.m4a': 'audio/mp4',
            '.aac': 'audio/aac',
            '.ogg': 'audio/ogg',
            '.flac': 'audio/flac'
        }
        audio_mime_type = mime_type_map.get(ext.lower(), 'audio/mpeg')

        # Use a directory-owned path rather than an open NamedTemporaryFile.
        # Windows locks the latter and prevents the storage adapter from
        # replacing it during download.
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file_path = os.path.join(temp_dir, f"audio{ext}")
            # Download the audio file from S3 to a temp file
            success = await s3_utils.download_file(audio_url, temp_file_path)
            if not success:
                logger.error(f"无法下载音频文件: {audio_url}")
                return None

            # Read the audio file asynchronously
            async with aiofiles.open(temp_file_path, "rb") as audio_file:
                audio_bytes = await audio_file.read()

            # Get the actual audio duration for validation
            logger.info("🎵 获取音频实际时长...")
            actual_duration = await get_audio_duration(audio_url)
            if actual_duration is None:
                logger.error("🎵 无法获取音频实际时长")
                return None

            logger.info(f"🎵 音频实际时长: {actual_duration:.2f}s")

            # Gemini request body inline is ~20MB limited, ~4/3 after base64, so use file_uri when the original is >15MB
            _AUDIO_INLINE_SIZE_LIMIT = 15 * 1024 * 1024  # 15MB
            if len(audio_bytes) > _AUDIO_INLINE_SIZE_LIMIT:
                from app.utils.google_file_upload import upload_audio_to_google
                file_uri, google_mime = await upload_audio_to_google(temp_file_path, max_wait_time=300)
                if file_uri:
                    # ⚠️ When using file_uri, mime_type must be the actual type recognized by the Google Files API
                    # (e.g. audio/x-wav), not our own mapped audio/wav, otherwise Gemini returns 400
                    effective_mime = google_mime or audio_mime_type
                    audio_content = {"file_uri": file_uri, "mime_type": effective_mime}
                    logger.info(f"🎵 大音频使用 file_uri 发送（{len(audio_bytes) / (1024*1024):.2f} MB, mime={effective_mime}）")
                else:
                    logger.warning("🎵 上传 Google 失败，降级为 base64（可能超 20MB 被 Gemini 拒绝）")
                    encoded_audio = base64.b64encode(audio_bytes).decode("utf-8")
                    audio_content = {"data": encoded_audio, "mime_type": audio_mime_type}
            else:
                encoded_audio = base64.b64encode(audio_bytes).decode("utf-8")
                audio_content = {"data": encoded_audio, "mime_type": audio_mime_type}

            from google import genai
            from google.genai import types
            from app.models.tool_enums import ToolProvider, ToolType
            from app.services.account.account_router import get_account_router

            _apply_lipsync = should_apply_lipsync_constraint(
                user_option,
                music_intent=music_intent,
                music_workflow_mode=music_workflow_mode,
            )
            _granularity = _resolve_granularity(granularity)

            from app.chat.v2.language import (
                apply_media_analysis_language,
                language_contract_payload,
            )

            contract = language_contract_payload(language_contract)
            facts = {
                "audio_duration_sec": round(float(actual_duration), 2),
                "user_input": (user_input or "").strip(),
                "generated_lyrics": (generated_lyrics or "").strip(),
                "suno_alignment_context": (suno_alignment_context or "").strip(),
                "apply_lipsync_constraint": bool(_apply_lipsync),
                "lipsync_max_segment_duration": (
                    get_lipsync_max_segment_duration(user_option) if _apply_lipsync else None
                ),
                "granularity": _granularity.value,
            }
            if contract is not None:
                facts["content_language"] = contract["content_language"]
            prompt = (
                "Transcribe and analyze the attached audio. Return JSON matching the "
                "provided schema exactly. Use MM:SS.mmm timestamps, keep every segment "
                "within the measured audio duration, identify song sections, vocals, "
                "tempo, emotion, and word timestamps when audible. Runtime facts:\n"
                + json.dumps(facts, ensure_ascii=False)
            )
            from app.chat.v2.media_prompts import media_system_instruction
            system_instruction = apply_media_analysis_language(
                media_system_instruction("audio-transcription-director"),
                contract,
            )
            if "file_uri" in audio_content:
                audio_part = types.Part.from_uri(
                    file_uri=audio_content["file_uri"],
                    mime_type=audio_content["mime_type"],
                )
            else:
                audio_part = types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type=audio_content["mime_type"],
                )

            async def _transcribe_request(api_key: str):
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=300_000),
                )
                return await client.aio.models.generate_content(
                    model=ToolType.GEMINI_2_5_FLASH.value,
                    contents=types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=prompt), audio_part],
                    ),
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=GeminiTranscriptionResult,
                    ),
                )

            # Retry logic: retry up to 3 times, collect all results, then pick the best
            max_retries = 3
            retry_count = 0
            gemini_result = None
            all_results = []  # keep the results of all attempts

            while retry_count < max_retries:
                logger.info(f"🎵 调用 Gemini 模型进行音频转录... (尝试 {retry_count + 1}/{max_retries})")
                router = await get_account_router()
                response = await router.route_tool_request(
                    provider=ToolProvider.GOOGLE,
                    tool_type=ToolType.GEMINI_2_5_FLASH,
                    request_func=_transcribe_request,
                )
                raw_result = getattr(response, "parsed", None)
                if raw_result is None and getattr(response, "text", None):
                    raw_result = json.loads(response.text)
                if raw_result is None:
                    logger.error(f"🎵 Gemini 转录失败：无法解析结果 (尝试 {retry_count + 1})")
                    retry_count += 1
                    continue
                temp_result = (
                    raw_result
                    if isinstance(raw_result, GeminiTranscriptionResult)
                    else GeminiTranscriptionResult.model_validate(raw_result)
                )

                # Parse the duration returned by Gemini (MM:SS.mmm to seconds)
                gemini_duration_seconds = parse_time_to_seconds(temp_result.duration)

                # Validate the total duration
                duration_diff = abs(gemini_duration_seconds - actual_duration)

                # Validate whether any segment timestamp exceeds the actual audio duration (hard criterion)
                invalid_segments_actual = []
                for i, segment in enumerate(temp_result.segments):
                    segment_start = parse_time_to_seconds(segment.start)
                    segment_end = parse_time_to_seconds(segment.end)
                    if segment_start > actual_duration or segment_end > actual_duration:
                        invalid_segments_actual.append(f"片段{i+1}({segment.start}-{segment.end})")

                # Validate whether any segment timestamp exceeds the total duration Gemini itself reported
                invalid_segments_gemini = []
                for i, segment in enumerate(temp_result.segments):
                    segment_start = parse_time_to_seconds(segment.start)
                    segment_end = parse_time_to_seconds(segment.end)
                    if segment_start > gemini_duration_seconds or segment_end > gemini_duration_seconds:
                        invalid_segments_gemini.append(f"片段{i+1}({segment.start}-{segment.end})")

                logger.info(f"🎵 Gemini 转录完成 (尝试 {retry_count + 1}): 语言={temp_result.language}, 时长={temp_result.duration}({gemini_duration_seconds:.2f}s), 片段数={len(temp_result.segments)}")
                logger.info(f"🎵 时长对比: Gemini={gemini_duration_seconds:.2f}s, 实际={actual_duration:.2f}s, 误差={duration_diff:.2f}s")

                if invalid_segments_actual:
                    logger.warning(f"⚠️ 发现{len(invalid_segments_actual)}个时间戳超出实际音频时长的片段: {', '.join(invalid_segments_actual)}")
                if invalid_segments_gemini:
                    logger.warning(f"⚠️ 发现{len(invalid_segments_gemini)}个时间戳超出Gemini自己给出的时长的片段: {', '.join(invalid_segments_gemini)}")

                # Save the result and related info
                result_info = {
                    'result': temp_result,
                    'duration_diff': duration_diff,
                    'invalid_segments_actual': invalid_segments_actual,
                    'invalid_segments_gemini': invalid_segments_gemini,
                    'attempt': retry_count + 1
                }
                all_results.append(result_info)

                # Pass condition: duration error <= 2s and no timestamps exceed Gemini's own reported duration
                if duration_diff <= 2.0 and not invalid_segments_gemini:
                    gemini_result = temp_result
                    logger.info(f"✅ 验证通过：时长误差 {duration_diff:.2f}s <= 2.0s，所有时间戳都在Gemini给出的时长范围内")
                    break
                else:
                    if duration_diff > 2.0:
                        logger.warning(f"⚠️ 时长误差过大 {duration_diff:.2f}s > 2.0s")
                    if invalid_segments_gemini:
                        logger.warning(f"⚠️ 有{len(invalid_segments_gemini)}个片段时间戳超出Gemini自己给出的时长")
                    logger.warning("重试...")
                    retry_count += 1

            # If no retry met the condition, pick the best result
            if gemini_result is None and all_results:
                logger.warning(f"🎵 {max_retries} 次尝试后都未完全通过验证，开始选择最佳结果")

                # First filter out results whose timestamps exceed the actual audio duration (hard criterion)
                valid_results = [r for r in all_results if not r['invalid_segments_actual']]

                if valid_results:
                    # Among results meeting the hard criterion, pick the one with the smallest duration difference
                    best_result = min(valid_results, key=lambda x: x['duration_diff'])
                    gemini_result = best_result['result']
                    logger.info(f"✅ 选择最佳结果：尝试{best_result['attempt']}，时长误差{best_result['duration_diff']:.2f}s，无时间戳超出实际音频时长")
                else:
                    # If all results have timestamps exceeding the actual duration, pick the one with the smallest duration difference
                    best_result = min(all_results, key=lambda x: x['duration_diff'])
                    gemini_result = best_result['result']
                    logger.warning(f"⚠️ 所有结果都有时间戳问题，选择时长误差最小的：尝试{best_result['attempt']}，时长误差{best_result['duration_diff']:.2f}s")
            elif gemini_result is None:
                logger.error("🎵 Gemini 转录完全失败：无法获得任何结果")
                return None

        # Convert to AudioSegment format, MM:SS.mmm to seconds
        audio_segments = []
        for i, segment in enumerate(gemini_result.segments):
            start_seconds = parse_time_to_seconds(segment.start)
            end_seconds = parse_time_to_seconds(segment.end)
            duration_seconds = end_seconds - start_seconds

            audio_segments.append(AudioSegment(
                id=i,
                start=start_seconds,
                end=end_seconds,
                text=segment.text,
                duration=duration_seconds,
                emotion=segment.emotion,
                tempo=segment.tempo,
                vocal_presence=getattr(segment, "vocal_presence", None),
                vocal_gender=getattr(segment, "vocal_gender", None) if getattr(segment, "vocal_gender", None) in ("f", "m") else None,
            ))

        # Skip words data for now, but keep the processing logic for future restoration
        words_data = []
        # Get words via getattr; None if absent
        gemini_words = getattr(gemini_result, 'words', None)
        if gemini_words:
            from app.models.video_state import AudioWord
            for word in gemini_words:
                words_data.append(AudioWord(
                    id=word.id,
                    word=word.word,
                    start=parse_time_to_seconds(word.start),
                    end=parse_time_to_seconds(word.end)
                ))
            logger.info(f"🎵 Gemini提取了 {len(words_data)} 个 words")
        else:
            logger.info("🎵 Gemini 未返回 words 数据（已暂时禁用）")

        sections_list: List[Dict[str, Any]] = []
        if gemini_result.sections and len(gemini_result.sections) > 0:
            sections_list = [
                {
                    "section_type": s.section_type,
                    "start_time": parse_time_to_seconds(s.start_seconds),
                    "end_time": parse_time_to_seconds(s.end_seconds),
                    "musical_features": s.musical_features,
                    "section_emotion": s.section_emotion,
                    "suggested_visual_intensity": s.suggested_visual_intensity,
                    "suggested_rhythmic_strategy": s.suggested_rhythmic_strategy,
                    "suggested_visual_theme": s.suggested_visual_theme,
                    "suggested_context": s.suggested_context,
                }
                for s in gemini_result.sections
            ]
        if fill_gaps and audio_segments:
            audio_segments, sections_list = postprocess_transcription(
                audio_segments,
                sections_list or None,
                total_duration=actual_duration,
                fill_gaps_enabled=True,
            )

        # Split-granularity post-processing (only triggers in beat mode; sentence/phrase rely entirely on prompt guidance)
        if audio_segments and _granularity == AudioSegmentGranularity.BEAT:
            bpm_val = getattr(gemini_result, "global_bpm", None)
            if bpm_val and float(bpm_val) > 0:
                bar_dur = 240.0 / float(bpm_val)
                word_edges_sec: List[float] = []
                if getattr(gemini_result, "words", None):
                    for w in gemini_result.words:
                        try:
                            word_edges_sec.append(parse_time_to_seconds(w.start))
                            word_edges_sec.append(parse_time_to_seconds(w.end))
                        except Exception:
                            pass
                snapped = snap_segment_edges_to_bar_grid(
                    audio_segments,
                    bar_dur_sec=bar_dur,
                    tolerance_sec=min(0.20, bar_dur * 0.25),
                    word_edges_sec=word_edges_sec,
                    total_duration=actual_duration,
                )
                logger.info(
                    "🥁 beat 后处理：BPM=%.1f, bar_dur=%.3fs, segments=%d → %d（端点吸附到小节线，遇词内自动漂移）",
                    float(bpm_val), bar_dur, len(audio_segments), len(snapped),
                )
                audio_segments = snapped
            else:
                logger.warning(
                    "🥁 beat 模式但 Gemini 未给出 global_bpm，跳过小节吸附（segments 保留原 LLM 输出）"
                )

        # Build additional_data, storing Gemini's raw data (keeping the original MM:SS.mmm format)
        additional_data = {
            "gemini_segments": [
                {
                    "id": i,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                    "duration": seg.duration,
                    "emotion": seg.emotion,
                    "tempo": seg.tempo,
                    "vocal_presence": getattr(seg, "vocal_presence", None),
                    "vocal_gender": getattr(seg, "vocal_gender", None),
                    "section_index": getattr(seg, "section_index", None),
                    "start_seconds": parse_time_to_seconds(seg.start),
                    "end_seconds": parse_time_to_seconds(seg.end),
                    "duration_seconds": parse_time_to_seconds(seg.end) - parse_time_to_seconds(seg.start)
                }
                for i, seg in enumerate(gemini_result.segments)
            ],
            "transcription_method": "gemini",
            "is_instrumental": gemini_result.is_instrumental,  # whether it is instrumental
            "original_duration": gemini_result.duration,  # duration reported by Gemini (MM:SS.mmm)
            "duration_seconds": parse_time_to_seconds(gemini_result.duration),  # duration reported by Gemini (seconds)
            "actual_duration_seconds": actual_duration,  # actual audio duration (seconds)
            "audio_segment_granularity": _granularity.value,  # this run's split granularity (phrase/sentence/beat), for downstream audit
        }
        # Whole-track Global, for music_generation_service to write into video_audio_transcription
        if gemini_result.song_name is not None:
            additional_data["song_name"] = gemini_result.song_name
        if gemini_result.global_bpm is not None:
            additional_data["global_bpm"] = float(gemini_result.global_bpm)
        if gemini_result.genre is not None:
            additional_data["genre"] = gemini_result.genre
        if gemini_result.global_emotion is not None:
            additional_data["global_emotion"] = gemini_result.global_emotion
        if gemini_result.suggested_global_theme is not None:
            additional_data["suggested_global_theme"] = gemini_result.suggested_global_theme
        if gemini_result.suggested_color_palette is not None:
            additional_data["suggested_color_palette"] = gemini_result.suggested_color_palette
        # Song Structure sections, for music_generation_service to write into video_audio_section
        if sections_list:
            additional_data["sections"] = sections_list
        elif gemini_result.sections and len(gemini_result.sections) > 0:
            additional_data["sections"] = [
                {
                    "section_type": s.section_type,
                    "start_time": parse_time_to_seconds(s.start_seconds),
                    "end_time": parse_time_to_seconds(s.end_seconds),
                    "musical_features": s.musical_features,
                    "section_emotion": s.section_emotion,
                    "suggested_visual_intensity": s.suggested_visual_intensity,
                    "suggested_rhythmic_strategy": s.suggested_rhythmic_strategy,
                    "suggested_visual_theme": s.suggested_visual_theme,
                    "suggested_context": s.suggested_context,
                }
                for s in gemini_result.sections
            ]
            _sync_section_end_times_to_segments(
                additional_data["sections"],
                audio_segments,
                actual_duration,
            )
        else:
            additional_data["sections"] = fallback_full_track_sections(
                actual_duration,
                audio_segments,
                global_emotion=gemini_result.global_emotion,
            )
            logger.info(
                "🎵 未返回曲式段落，已后置注入默认整轨 section [0, %.2f)s",
                additional_data["sections"][0]["end_time"],
            )

        # Skip saving words data for now, but keep the processing logic for future restoration
        gemini_words = getattr(gemini_result, 'words', None)
        if gemini_words:
            additional_data["gemini_words"] = [
                {
                    "id": word.id,
                    "word": word.word,
                    "start": word.start,
                    "end": word.end
                }
                for word in gemini_words
            ]
            # For Whisper compatibility, also store words data in the standard "words" field
            additional_data["words"] = [
                {
                    "id": word.id,
                    "word": word.word,
                    "start": word.start,
                    "end": word.end
                }
                for word in gemini_words
            ]

        result = AudioTranscription(
            task=gemini_result.task,
            language=gemini_result.language,
            duration=actual_duration,  # use the actual audio duration instead of Gemini's reported one
            text=gemini_result.text,
            segments=audio_segments,  # processed segments (already gap-filled and merged)
            audio_url=audio_url,
            filename=filename,  # original file name
            is_instrumental=gemini_result.is_instrumental,  # whether it is instrumental
            additional_data=additional_data  # Gemini raw data (includes Gemini's reported duration as reference)
        )

        logger.info(f"🎵 Gemini 音频转录完成: 语言={result.language}, 时长={result.duration:.2f}s, 片段数={len(result.segments)}")

        return result

    except Exception as e:
        logger.error(f"Gemini 音频转录失败: {audio_url}, 错误: {e}")
        return None


async def transcribe_audio(
    audio_url: str,
    method: str = "gemini",
    user_option: Optional[UserOption] = None,
    fill_gaps: bool = True,
    user_input: Optional[str] = None,
    filename: Optional[str] = None
) -> Optional[AudioTranscription]:
    """
    Unified audio-transcription interface (Gemini only).

    Args:
        audio_url: CDN URL of the audio file
        method: transcription method, only "gemini" is supported (default)
        user_option: user-option configuration
        fill_gaps: whether to fill missing time gaps
        user_input: user-provided content (may include lyrics)
        filename: original audio file name

    Returns:
        Optional[AudioTranscription]: transcription result, None on failure
    """
    logger.info("🎵 使用 Gemini 进行音频转录")
    return await transcribe_audio_with_gemini(
        audio_url=audio_url,
        user_option=user_option,
        fill_gaps=fill_gaps,
        user_input=user_input,
        filename=filename
    )
