"""
Video planning durations: discrete seconds list + scene-split/planning preferences.

Design (aligned with OpenMontage scene_plan):
- **LLM** writes wall-clock durations (scene.duration / script section windows)
- **Code** only provides: API-generatable seconds table (clamp) + prefer hint (leans to 8s)
- Do not treat the API min (often 3/4) as the "recommended per-scene duration"

- seconds list: intersection of the wrapper chain's supported_duration_seconds
- prefer / split: video_tool_profiles.scene_split_threshold_sec, otherwise preferred_planning_unit
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.agent_config.video_tool_profiles import (
    resolve_audio_driven_scene_split_threshold,
    resolve_scene_split_threshold,
)
from app.models.user_options import UserOption
from app.services.agent.utils.video_tool_duration_capabilities import (
    AUDIO_DRIVEN_PLANNING_DURATION_VALUES,
    VIDEO_DRIVEN_PLANNING_DURATION_VALUES,
    get_audio_driven_duration_values_for_user,
    get_video_driven_duration_values_for_user,
)


def get_audio_driven_duration_values(user_option: Optional[UserOption] = None) -> List[int]:
    """Discrete seconds for audio-driven planning: scene splitting, transcription max_segment, same source as scene_structure."""
    if user_option is None:
        return list(AUDIO_DRIVEN_PLANNING_DURATION_VALUES)
    return get_audio_driven_duration_values_for_user(user_option)


def get_video_driven_duration_values(user_option: Optional[UserOption] = None) -> List[int]:
    """Discrete seconds for video-driven planning: outline/scene constraints, tier selection for normal I2V output."""
    if user_option is None:
        return list(VIDEO_DRIVEN_PLANNING_DURATION_VALUES)
    return get_video_driven_duration_values_for_user(user_option)


def get_audio_driven_split_threshold(
    user_option: Optional[UserOption] = None,
    content_category: Optional[str] = None,
) -> float:
    """Audio-driven scene-split threshold (seconds). content_category reserved."""
    del content_category  # reserved
    if user_option is None:
        return float(min(AUDIO_DRIVEN_PLANNING_DURATION_VALUES)) if AUDIO_DRIVEN_PLANNING_DURATION_VALUES else 5.0
    values = get_audio_driven_duration_values(user_option)
    return resolve_audio_driven_scene_split_threshold(
        user_option, audio_driven_duration_values=values
    )


def get_video_driven_split_threshold(user_option: Optional[UserOption] = None) -> float:
    """Video-driven planning prefer / cost-estimation threshold (seconds).

    Same source as audio-driven: profile (pollo/SD2=8) takes priority; do not use min(API)=3.
    The real per-scene duration is still designed by the LLM at the scene stage; this value is only for estimation and brief hints.
    """
    if user_option is None:
        return float(preferred_planning_unit(VIDEO_DRIVEN_PLANNING_DURATION_VALUES))
    values = get_video_driven_duration_values(user_option)
    return resolve_scene_split_threshold(user_option, duration_values=values)


def preferred_planning_unit(allowed_durations: Optional[List[int]] = None) -> int:
    """Preferred unit for chapter/correction reallocation (leans to 8s, close to short-drama dialogue scenes / OM hero)."""
    allowed = sorted({int(d) for d in (allowed_durations or []) if int(d) > 0})
    if not allowed:
        return 8
    for pref in (8, 10, 5, 6, 7, 9, 4):
        if pref in allowed:
            return pref
    return min(allowed, key=lambda d: (abs(d - 8), d))


def api_min_duration(allowed_durations: Optional[List[int]] = None) -> int:
    """Tool chain's minimum generatable seconds (clamp lower bound, not a recommended scene length)."""
    allowed = sorted({int(d) for d in (allowed_durations or []) if int(d) > 0})
    return int(allowed[0]) if allowed else 3


def planning_duration_hints(
    user_option: Optional[UserOption] = None,
) -> Tuple[List[int], int, int]:
    """Return (allowed_durations, preferred_sec, api_min_sec) for video-driven briefs."""
    allowed = get_video_driven_duration_values(user_option)
    pref = int(get_video_driven_split_threshold(user_option)) if user_option else preferred_planning_unit(allowed)
    # keep preferred inside allowed when possible
    if allowed and pref not in allowed:
        pref = preferred_planning_unit(allowed)
    return allowed, pref, api_min_duration(allowed)


def scene_count_unit(allowed_durations: Optional[List[int]] = None) -> int:
    """Soft-guidance scene-count unit: leans to 8s (OM dialogue/montage sweet spot), no longer using 5 to cut 30s into 6 scenes."""
    return preferred_planning_unit(allowed_durations)


def short_drama_min_scenes(chapter_duration: float, count_unit: int = 8) -> int:
    """Suggested scene count (soft guidance only; the code must not force shot splitting).

    OM style: fewer, denser scenes (about 5-11s), not 3-4s micro-cuts.
    e.g. 8s->1; 12s->1-2; 30s->3-4.
    """
    chapter = float(chapter_duration or 0)
    unit = max(6, int(count_unit or 8))
    if chapter < 10:
        return 1
    return max(1, int(round(chapter / unit)))


# compat with the old name: the meaning has generalized to a generic suggested scene count
suggested_min_scenes = short_drama_min_scenes


def allocate_durations_summing_to_target(
    target_duration: float,
    part_count: int,
    unit: int,
) -> List[float]:
    """Distribute target_duration across part_count segments, preferring integer multiples of unit, with the sum exactly equal to target and no negatives.

    e.g. target=30, parts=3, unit=5 -> [10, 10, 10]
    e.g. target=30, parts=1, unit=5 -> [30]
    """
    if part_count <= 0:
        return []
    target = float(target_duration)
    if part_count == 1:
        return [target]

    unit = max(1, int(unit))
    target_floor = int(target)
    frac = target - target_floor
    total_units = target_floor // unit
    rem_secs = target_floor - total_units * unit

    if total_units >= part_count:
        base_units = total_units // part_count
        extra_units = total_units % part_count
        durs = [
            float(base_units * unit + (unit if i < extra_units else 0))
            for i in range(part_count)
        ]
        durs[-1] += rem_secs + frac
    else:
        base = target / part_count
        durs = [base] * (part_count - 1)
        durs.append(target - sum(durs))

    for i in range(part_count - 1):
        if durs[i] < 0:
            durs[i] = 0.0
    durs[-1] = target - sum(durs[:-1])
    if durs[-1] < 0:
        pos = [max(0.0, d) for d in durs[:-1]]
        s = sum(pos)
        if s <= 0:
            even = target / part_count
            return [even] * (part_count - 1) + [target - even * (part_count - 1)]
        scale = (target * 0.999) / s if target > 0 else 0.0
        durs = [p * scale for p in pos]
        durs.append(target - sum(durs))
    return durs
