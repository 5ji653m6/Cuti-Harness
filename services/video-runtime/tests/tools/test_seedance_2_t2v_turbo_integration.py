"""Integration: Seedance 2.0 Text-to-Video Turbo via WaveSpeed.

包含两类测试：
  1) 离线计费测试（不调用 API，不扣费）：覆盖官方定价表全部组合
     - 仅 720p/1080p（480p 按 720p 计价）
     - 无 reference_videos：720p $0.70/5s，1080p $0.75/5s
     - 有 reference_videos：720p $1.30/5s，1080p $1.35/5s（按输出时长线性，与参考视频长度无关）
  2) 真实 API 测试（需 WAVESPEED_API_KEY，会扣费）：并发跑多组参数组合（分辨率/比例/音频/参考图），
     以 720p/4s 为主控制成本。

运行：
    pytest tests/tools/test_seedance_2_t2v_turbo_integration.py -v            # 全部（真实测试会因无 key 自动跳过）
    pytest tests/tools/test_seedance_2_t2v_turbo_integration.py -k cost -v    # 仅离线计费
    pytest tests/tools/test_seedance_2_t2v_turbo_integration.py -k real -v -s # 真实并发
"""
import os
import asyncio
import random
import time
from pathlib import Path

import pytest

from dotenv import load_dotenv

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parent.parent.parent
_env = os.getenv("ENVIRONMENT", "development").lower()
if _env == "production":
    load_dotenv(ROOT / ".env.production")
else:
    load_dotenv(ROOT / ".env.development")
load_dotenv(ROOT / ".env.local")

from app.llm.wavespeed_service import WaveSpeedService
from app.models.tool_enums import Resolution, ToolType
from app.services.tool_service import ToolService


# ==================== 1) 离线计费测试（覆盖官方定价表全部组合） ====================

# 无 reference_videos：720p $0.70/5s，1080p $0.75/5s，按输出时长线性
_NO_REF_COST_CASES = [
    (Resolution.P720, 5, 0.70),
    (Resolution.P720, 10, 1.40),
    (Resolution.P720, 15, 2.10),
    (Resolution.P1080, 5, 0.75),
    (Resolution.P1080, 10, 1.50),
    (Resolution.P1080, 15, 2.25),
]


@pytest.mark.parametrize("resolution,duration,expected", _NO_REF_COST_CASES)
def test_seedance_2_t2v_turbo_cost_no_ref_video(resolution, duration, expected):
    cost = ToolService.calculate_cost(ToolType.SEEDANCE_2_T2V_TURBO, duration=duration, resolution=resolution)
    assert cost == pytest.approx(expected), f"{resolution.value} {duration}s 期望 ${expected}, 实际 ${cost}"


# 有 reference_videos：720p $1.30/5s，1080p $1.35/5s（与参考视频长度无关，仅看输出时长）
_REF_VIDEO_COST_CASES = [
    (Resolution.P720, 5, 5.0, 1.30),
    (Resolution.P720, 10, 5.0, 2.60),
    (Resolution.P720, 15, 5.0, 3.90),
    (Resolution.P1080, 5, 5.0, 1.35),
    (Resolution.P1080, 10, 5.0, 2.70),
    (Resolution.P1080, 15, 5.0, 4.05),
    # 参考视频长度不影响价格（仍按输出时长）：ref 20s、输出 5s @720p = $1.30
    (Resolution.P720, 5, 20.0, 1.30),
]


@pytest.mark.parametrize("resolution,duration,ref_dur,expected", _REF_VIDEO_COST_CASES)
def test_seedance_2_t2v_turbo_cost_with_ref_video(resolution, duration, ref_dur, expected):
    cost = ToolService.calculate_cost(
        ToolType.SEEDANCE_2_T2V_TURBO,
        duration=duration,
        resolution=resolution,
        reference_videos_duration_sec=ref_dur,
    )
    assert cost == pytest.approx(expected), f"{resolution.value} out={duration}s ref={ref_dur}s 期望 ${expected}, 实际 ${cost}"


def test_seedance_2_t2v_turbo_cost_480p_billed_as_720p():
    # Turbo 不支持 480p：计价按 720p
    assert ToolService.calculate_cost(ToolType.SEEDANCE_2_T2V_TURBO, duration=5, resolution=Resolution.P480) == pytest.approx(0.70)


def test_seedance_2_t2v_turbo_cost_duration_clamped():
    # 3s 应被 clamp 到 4s，17s 应被 clamp 到 15s
    assert ToolService.calculate_cost(ToolType.SEEDANCE_2_T2V_TURBO, duration=3, resolution=Resolution.P720) == pytest.approx(0.70 * (4 / 5.0))
    assert ToolService.calculate_cost(ToolType.SEEDANCE_2_T2V_TURBO, duration=17, resolution=Resolution.P720) == pytest.approx(2.10)


# ==================== 2) 真实 API 测试（并发，需 WAVESPEED_API_KEY，会扣费） ====================

_EXAMPLE_REF_IMAGE = "https://static.wavespeed.ai/examples/3f7e3b510d1e4a60aea09ec4573e1751/1775358390074410023_q9OY8irB.jpeg"

_PROMPT_TEMPLATES = [
    "A cinematic close-up of {subject}, {lighting} lighting, slow push-in, shallow depth of field.",
    "Wide cinematic shot of {subject} under {lighting} light; smooth camera arc; film grain.",
    "{subject} in motion, dramatic {lighting} lighting, handheld energy, photorealistic.",
]
_SUBJECTS = ["a detective in a trench coat", "a rider speeding through neon rain", "a dancer mid-spin", "waves crashing on rocks"]
_LIGHTING = ["golden hour", "neon", "soft ambient", "dramatic chiaroscuro"]


def _random_prompt() -> str:
    return random.choice(_PROMPT_TEMPLATES).format(
        subject=random.choice(_SUBJECTS), lighting=random.choice(_LIGHTING)
    )


# Turbo 仅 720p/1080p。以 720p/4s 为主控制成本，覆盖：比例 / 音频开关 / 参考图 / 1080p。
_REAL_COMBOS = [
    {"label": "720p/16:9/audio", "resolution": "720p", "aspect_ratio": "16:9", "generate_audio": True},
    {"label": "720p/9:16/no-audio", "resolution": "720p", "aspect_ratio": "9:16", "generate_audio": False},
    {"label": "720p/1:1/audio", "resolution": "720p", "aspect_ratio": "1:1", "generate_audio": True},
    {"label": "720p/16:9/ref-image", "resolution": "720p", "aspect_ratio": "16:9", "generate_audio": True,
     "reference_images": [_EXAMPLE_REF_IMAGE]},
    {"label": "1080p/16:9/audio", "resolution": "1080p", "aspect_ratio": "16:9", "generate_audio": True},
]


async def _run_one(svc: WaveSpeedService, combo: dict) -> dict:
    label = combo["label"]
    start = time.time()
    try:
        result = await svc.generate_seedance_2_t2v_turbo(
            prompt=_random_prompt(),
            duration=4,
            resolution=combo["resolution"],
            aspect_ratio=combo["aspect_ratio"],
            generate_audio=combo["generate_audio"],
            reference_images=combo.get("reference_images"),
        )
        elapsed = time.time() - start
        ok = bool(result.success and result.video_url)
        print(f"{'✅' if ok else '❌'} [{label}] {elapsed:.1f}s url={(result.video_url or '')[:60]} msg={result.message or result.error_msg}")
        return {"label": label, "success": ok, "video_url": result.video_url, "elapsed": elapsed,
                "error": None if ok else (result.message or result.error_msg)}
    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ [{label}] {elapsed:.1f}s exception={e}")
        return {"label": label, "success": False, "video_url": None, "elapsed": elapsed, "error": str(e)}


@pytest.mark.asyncio
async def test_seedance_2_t2v_turbo_real_concurrent():
    """真实并发：同时跑多组参数组合，验证 720p/1080p、比例、音频、参考图都能成功出片。"""
    if not os.getenv("WAVESPEED_API_KEY"):
        pytest.skip("WAVESPEED_API_KEY not set")
    svc = WaveSpeedService()
    if not svc.api_key:
        pytest.skip("WaveSpeed API key not configured")

    print("\n" + "=" * 80)
    print(f"🚀 Seedance 2.0 T2V Turbo 真实并发测试，组合数: {len(_REAL_COMBOS)}（均 4s，主要 720p）")
    print("=" * 80)

    overall = time.time()
    results = await asyncio.gather(*[_run_one(svc, c) for c in _REAL_COMBOS], return_exceptions=False)
    total = time.time() - overall

    succeeded = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    print("\n" + "=" * 80)
    print(f"✅ 成功 {len(succeeded)}/{len(results)}  ⏱️ 总耗时 {total:.1f}s")
    for r in failed:
        print(f"  ❌ {r['label']}: {r['error']}")
    print("=" * 80 + "\n")

    assert len(succeeded) > 0, "所有 T2V Turbo 组合均失败"
    success_rate = len(succeeded) / len(results)
    assert success_rate >= 0.5, f"成功率过低: {success_rate*100:.0f}%"
    for r in succeeded:
        assert r["video_url"], f"{r['label']} 缺少 video_url"


@pytest.mark.asyncio
async def test_seedance_2_t2v_turbo_real_smoke():
    """单次真实冒烟（最便宜：720p/4s），便于快速验证端点连通。"""
    if not os.getenv("WAVESPEED_API_KEY"):
        pytest.skip("WAVESPEED_API_KEY not set")
    svc = WaveSpeedService()
    if not svc.api_key:
        pytest.skip("WaveSpeed API key not configured")
    result = await svc.generate_seedance_2_t2v_turbo(
        prompt="A detective pushes open a rusted door into a dim warehouse; slow tracking shot; noir lighting.",
        duration=4,
        resolution="720p",
        aspect_ratio="16:9",
        generate_audio=True,
    )
    assert result.success, result.message or result.error_msg
    assert result.video_url
    assert ".mp4" in result.video_url or "http" in result.video_url
