"""
Auto lyrics 时长验证测试（传 lyrics 已单独调整过，本文件只测 auto_lyrics）

- 验证1/2/3：auto_lyrics 行为与 LLM 流程（baseline、显式时长、完整 LLM 调用）
- auto_lyrics 多档位：从 0–300s 取代表性子（极短/短/标准/长），测试在目标误差内

运行（需 conda env cuti-video-local，且配置 SUNO_API_KEY）：
  pytest tests/tools/test_suno_auto_lyrics_duration.py -v -s
  pytest tests/tools/test_suno_auto_lyrics_duration.py -k "auto_lyrics_duration_targets" -v -s  # 仅多档位

全网格（5–300s 每 15s、连续命中、节流）请用脚本而非 pytest 长时间占线：
  conda run -n cuti-video-local python scripts/suno_duration_grid_experiment.py --dry-run
  conda run -n cuti-video-local python scripts/suno_duration_grid_experiment.py --sleep-sec 90 --max-error-sec 10 --streak 3
"""
import pytest

from app.tools.music.suno import _generate_music_with_suno_impl
from app.models.image_result import MusicProvider


pytestmark = pytest.mark.integration

# auto_lyrics 多档位：0–300s 代表性子（极短 30、短 60/90、标准 120、长 180/240/300），每档目标误差 ≤15s
AUTO_LYRICS_DURATION_TARGETS = [30, 60, 90, 120, 180, 240, 300]
MAX_DURATION_ERROR_SEC = 15

# 与用户报错场景一致的参数（仅 prompt + tags，无代码侧注入）
USER_PROMPT = (
    "这个人在操场上奔跑，镜头从脚部拉到全身，包含回头和侧面转头的镜头，"
    "以及从手部拉到脸部的镜头，整体氛围轻快活泼，适合短时长的带人声歌曲"
)
USER_TAGS = "Short version"
USER_TARGET_DURATION = 30


def _auto_lyrics_prompt_for_target(target_sec: int) -> str:
    """按目标时长返回带英文短时长句的 auto_lyrics 描述。"""
    base = "Upbeat song, running on playground, light and lively vibe, positive mood."
    if target_sec <= 30:
        return f"{base} Keep the song very short, around 30 seconds only, like a bumper or jingle."
    if target_sec <= 60:
        return f"{base} Keep the song short, around {target_sec} seconds only."
    if target_sec <= 90:
        return f"{base} Keep the song brief, around {target_sec} seconds."
    if target_sec <= 180:
        return f"{base} Keep the song around {target_sec} seconds."
    return base


def _tags_for_target(target_sec: int) -> str:
    """按目标时长返回 auto_lyrics 用的 tags。"""
    if target_sec <= 60:
        return "Short version, Jingle"
    if target_sec <= 90:
        return "Short version, Brief"
    return ""


def _print_duration_result(name: str, result, target_sec: int, max_error_sec: int = 20):
    """打印时长结果，便于对比验证。max_error_sec：用于打印结论的误差上限（多档位测试用 15）。"""
    print(f"\n{'='*60}")
    print(f"📋 {name}")
    print(f"   目标时长: {target_sec}s (允许误差 ≤{max_error_sec}s)")
    if result.success and result.clips:
        for i, clip in enumerate(result.clips):
            d = getattr(clip, "duration", None) or 0
            print(f"   Clip {i+1} 实际时长: {d}s (误差: {abs(d - target_sec)}s)")
        chosen = result.clips[0]
        chosen_d = getattr(chosen, "duration", None) or 0
        err = abs(chosen_d - target_sec)
        print(f"   选用: 第一个 clip → {chosen_d}s")
        print(f"   结论: {'✅ 在误差内' if err <= max_error_sec else '❌ 超出误差'}")
    else:
        print(f"   失败: {getattr(result, 'error', result.message or 'unknown')}")
    print("="*60 + "\n")


@pytest.mark.asyncio
async def test_auto_lyrics_baseline_same_as_user():
    """
    验证1：与用户完全一致的参数（prompt 无显式「30秒」字样，仅 tags='Short version'）。

    目的：看当前「仅靠 prompt 里已有描述 + Short version」时，Suno 实际给多长。
    若仍 ~2min，说明需要要么在描述里显式写短时长，要么代码里注入。
    """
    print("\n🎵 验证1：baseline（与用户参数一致，无代码注入）")
    print(f"   prompt: {USER_PROMPT[:80]}...")
    print(f"   tags: {USER_TAGS}, target_duration: {USER_TARGET_DURATION}")

    result = await _generate_music_with_suno_impl(
        prompt=USER_PROMPT,
        has_lyrics=False,
        auto_lyrics=True,
        target_duration=USER_TARGET_DURATION,
        tags=USER_TAGS,
        vocal_gender=None,
    )

    assert result.success is True, f"音乐生成失败: {result.error}"
    assert result.provider == MusicProvider.SUNO
    assert result.clips, "Clips 不应为空"

    _print_duration_result("Baseline（用户同参）", result, USER_TARGET_DURATION)


@pytest.mark.asyncio
async def test_auto_lyrics_prompt_with_explicit_duration():
    """
    验证2：在描述里显式写「30 秒、很短」（英文），tags 仍用 Short version。

    目的：验证「让 LLM 在 prompt 里写短时长」是否有效。若此用例明显短于 baseline，
    则后续可以靠 prompt 让 LLM 在描述里加这类句子，而不一定在代码里注入。
    """
    # 模拟 LLM 按要求在描述里加了显式时长
    prompt_with_duration = (
        "Someone running on a playground, camera from feet to full body, light and lively vibe, "
        "suitable for short vocal song. Keep the song very short, around 30 seconds only, like a bumper or jingle."
    )
    print("\n🎵 验证2：描述中显式写 30 秒（模拟 LLM 按要求写）")
    print(f"   prompt: {prompt_with_duration[:100]}...")
    print(f"   tags: {USER_TAGS}, target_duration: {USER_TARGET_DURATION}")

    result = await _generate_music_with_suno_impl(
        prompt=prompt_with_duration,
        has_lyrics=False,
        auto_lyrics=True,
        target_duration=USER_TARGET_DURATION,
        tags=USER_TAGS,
        vocal_gender=None,
    )

    assert result.success is True, f"音乐生成失败: {result.error}"
    assert result.provider == MusicProvider.SUNO
    assert result.clips, "Clips 不应为空"

    _print_duration_result("描述中显式 30 秒", result, USER_TARGET_DURATION)


@pytest.mark.parametrize("target_sec", AUTO_LYRICS_DURATION_TARGETS)
@pytest.mark.asyncio
async def test_auto_lyrics_duration_targets(target_sec: int):
    """
    auto_lyrics：从 0–300s 取代表性子（30/60/90/120/180/240/300），
    描述中含英文时长句 + tags，选用 clip 与目标误差不超过 15s。
    """
    prompt = _auto_lyrics_prompt_for_target(target_sec)
    tags = _tags_for_target(target_sec) or None
    print(f"\n🎵 auto_lyrics 目标 {target_sec}s, tags={tags!r}")

    result = await _generate_music_with_suno_impl(
        prompt=prompt,
        has_lyrics=False,
        auto_lyrics=True,
        target_duration=target_sec,
        tags=tags,
        vocal_gender=None,
    )

    assert result.success, f"音乐生成失败: {result.error}"
    assert result.clips, "Clips 不应为空"
    chosen_d = result.clips[0].duration or 0
    error_sec = abs(chosen_d - target_sec)
    _print_duration_result(f"auto_lyrics target={target_sec}s", result, target_sec, max_error_sec=MAX_DURATION_ERROR_SEC)
    assert error_sec <= MAX_DURATION_ERROR_SEC, (
        f"auto_lyrics 目标 {target_sec}s，实际 {chosen_d}s，误差 {error_sec}s 超过 {MAX_DURATION_ERROR_SEC}s"
    )
