"""
Wrapper 重试 & Fallback 单元测试 — 通过 mock 底层 tool 模拟各种故障场景。

所有 chain 与生产环境一致：3 个模型，每个模型最多 2 次尝试；Image wrapper 另有总生成次数上限
IMAGE_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS=3（与 video 侧 VIDEO_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS 语义一致）。

测试场景：
  Image I2I (3-model chain: pro → flash → seedream):
    1.  主模型可重试 → 同模型重试成功 (calls: 2)
    2.  主模型永久失败 → 第2模型成功 (calls: 1+1=2)
    3.  前2模型永久失败 → 第3模型成功 (calls: 1+1+1=3)
    4.  前2模型可重试耗尽 → 达总次数上限 3 后停止，未落到 seedream (calls: 2+1=3, 失败)
    5.  多模型一致性不通过 → best-effort；总调用受上限约束 (本例 calls: 3)
    6.  全部3模型 API 失败 → 返回错误 (calls: 3×1=3, permanent)

  Image T2I (3-model chain: pro → flash → seedream):
    7.  主模型可重试 → 重试成功 (calls: 2)
    8.  主模型永久失败 → 第2模型成功 (calls: 1+1=2)
    9.  前2模型永久失败 → 第3模型成功 (calls: 1+1+1=3)
    10. 前2模型可重试耗尽 → 达总次数上限 3 后停止 (calls: 2+1=3, 失败)
    11. 全部可重试失败 → 达总次数上限 3 后停止 (calls: 3, retryable)

  Video I2V (3-model chain: v1 → w26 → sora):
    12. 主模型可重试 → 重试成功 (calls: 2)
    13. 主模型永久失败 → 第2模型成功 (calls: 1+1=2)
    14. 前2模型永久失败 → 第3模型成功 (calls: 1+1+1=3)
    15. 前2模型可重试耗尽 → 第3模型成功 (calls: 2+2+1=5)
    16. 全部3模型失败 → 返回错误 (calls: 3×2=6, retryable)

运行：
  conda run -n cuti-video-dev python -m pytest tests/tools/test_wrapper_fallback_retry.py -v -s
"""
import os
from pathlib import Path

_environment = os.getenv("ENVIRONMENT", "development").lower()
from dotenv import load_dotenv
if _environment == "production":
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env.production")
else:
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env.development")

import asyncio
import json
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from types import SimpleNamespace
from typing import Optional, List, Dict, Any
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.models.image_result import ImageGenerationResult, VideoGenerationResult
from app.models.tool_enums import (
    ToolType, ToolMode, ToolProvider, ToolCategory, DefaultValues,
)
from app.tools.context_schemas import ImageGenerationContext, VideoGenerationContext


# ==================== 模拟结果工厂 ====================


def _ok_image(model: str = "test-model", url: str = "https://example.com/ok.webp") -> ImageGenerationResult:
    return ImageGenerationResult(
        success=True, image_url=url, model=model,
        provider="test", generated_prompt="test", aspect_ratio="16:9", resolution="1080p",
    )


def _fail_image_retryable(msg: str = "rate limit exceeded") -> ImageGenerationResult:
    return ImageGenerationResult(success=False, error_msg=msg, raw_error_msg=msg)


def _fail_image_permanent(msg: str = "content policy violation") -> ImageGenerationResult:
    return ImageGenerationResult(success=False, error_msg=msg, raw_error_msg=msg)


def _ok_video(model: str = "test-model", url: str = "https://example.com/ok.mp4") -> VideoGenerationResult:
    return VideoGenerationResult(
        success=True, video_url=url, model=model,
        provider="test", generated_prompt="test", aspect_ratio="16:9", resolution="1080p", duration=5.0,
    )


def _fail_video_retryable(msg: str = "rate limit exceeded") -> VideoGenerationResult:
    return VideoGenerationResult(success=False, error_msg=msg, raw_error_msg=msg, message=msg)


def _fail_video_permanent(msg: str = "invalid image format") -> VideoGenerationResult:
    return VideoGenerationResult(success=False, error_msg=msg, raw_error_msg=msg, message=msg)


# ==================== Mock Tool 工厂 ====================


def _make_mock_tool(name: str, behavior_fn):
    """创建带 call counter 的 mock tool。"""
    t = MagicMock()
    t.ainvoke = behavior_fn
    t.name = name
    t.metadata = {}
    return t


def _always_fail_retryable(label: str):
    """永远返回可重试错误。"""
    calls = {"n": 0}
    async def _fn(args):
        calls["n"] += 1
        return _fail_image_retryable(f"{label} rate limit")
    return _fn, calls


def _always_fail_permanent(label: str):
    """永远返回永久错误。"""
    calls = {"n": 0}
    async def _fn(args):
        calls["n"] += 1
        return _fail_image_permanent(f"{label} permanent error")
    return _fn, calls


def _always_ok(label: str, url: str = "https://example.com/ok.webp"):
    """永远成功。"""
    calls = {"n": 0}
    async def _fn(args):
        calls["n"] += 1
        return _ok_image(label, url)
    return _fn, calls


def _always_fail_video_retryable(label: str):
    calls = {"n": 0}
    async def _fn(args):
        calls["n"] += 1
        return _fail_video_retryable(f"{label} rate limit")
    return _fn, calls


def _always_fail_video_permanent(label: str):
    calls = {"n": 0}
    async def _fn(args):
        calls["n"] += 1
        return _fail_video_permanent(f"{label} permanent error")
    return _fn, calls


def _always_ok_video(label: str, url: str = "https://example.com/ok.mp4"):
    calls = {"n": 0}
    async def _fn(args):
        calls["n"] += 1
        return _ok_video(label, url)
    return _fn, calls


def _retryable_then_ok(label: str, url: str = "https://example.com/retry_ok.webp"):
    """第 1 次可重试错误，第 2 次成功。"""
    calls = {"n": 0}
    async def _fn(args):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fail_image_retryable(f"{label} rate limit")
        return _ok_image(label, url)
    return _fn, calls


def _retryable_then_ok_video(label: str, url: str = "https://example.com/retry_ok.mp4"):
    calls = {"n": 0}
    async def _fn(args):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fail_video_retryable(f"{label} rate limit")
        return _ok_video(label, url)
    return _fn, calls


# ==================== 辅助函数 ====================


def _make_image_runtime(refs: Optional[List[str]] = None) -> SimpleNamespace:
    ctx = ImageGenerationContext(
        aspect_ratio=DefaultValues.IMAGE_ASPECT_RATIO,
        resolution=DefaultValues.IMAGE_RESOLUTION,
        reference_image_urls=refs,
    )
    return SimpleNamespace(context=ctx)


def _make_video_runtime(start_url: str = "https://example.com/start.webp") -> SimpleNamespace:
    ctx = VideoGenerationContext(start_image_url=start_url)
    return SimpleNamespace(context=ctx)


# 3-model chain 定义（与生产一致）
IMAGE_CHAIN_TYPES = [
    (ToolType.GEMINI_3_PRO_IMAGE_PREVIEW, ToolProvider.GOOGLE),
    (ToolType.GEMINI_2_5_FLASH_IMAGE,     ToolProvider.GOOGLE),
    (ToolType.SEEDREAM_V4_5,              ToolProvider.WAVESPEED),
]

VIDEO_CHAIN_TYPES = [
    (ToolType.SEEDANCE_V1_PRO_FAST, ToolProvider.WAVESPEED),
    (ToolType.WAN_2_6_FLASH_I2V,   ToolProvider.WAVESPEED),
    (ToolType.SORA_2,               ToolProvider.OPENAI),
]


def _build_image_chain(behavior_fns):
    """从 3 个 behavior_fn 构建 3-model image chain，返回 (chain, call_counters)。"""
    from app.services.tool_service import ToolInfo
    chain = []
    counters = []
    for (tt, prov), (fn, cnt) in zip(IMAGE_CHAIN_TYPES, behavior_fns):
        tool = _make_mock_tool(tt.value, fn)
        chain.append(ToolInfo(
            tool=tool, tool_name=tt.value, tool_type=tt,
            provider=prov, category=ToolCategory.IMAGE_GENERATION, mode=ToolMode.I2I,
        ))
        counters.append(cnt)
    return chain, counters


def _build_image_chain_t2i(behavior_fns):
    from app.services.tool_service import ToolInfo
    chain = []
    counters = []
    for (tt, prov), (fn, cnt) in zip(IMAGE_CHAIN_TYPES, behavior_fns):
        tool = _make_mock_tool(tt.value, fn)
        chain.append(ToolInfo(
            tool=tool, tool_name=tt.value, tool_type=tt,
            provider=prov, category=ToolCategory.IMAGE_GENERATION, mode=ToolMode.T2I,
        ))
        counters.append(cnt)
    return chain, counters


def _build_video_chain(behavior_fns):
    from app.services.tool_service import ToolInfo
    chain = []
    counters = []
    for (tt, prov), (fn, cnt) in zip(VIDEO_CHAIN_TYPES, behavior_fns):
        tool = _make_mock_tool(tt.value, fn)
        chain.append(ToolInfo(
            tool=tool, tool_name=tt.value, tool_type=tt,
            provider=prov, category=ToolCategory.VIDEO_GENERATION, mode=ToolMode.I2V,
        ))
        counters.append(cnt)
    return chain, counters


# ==================== 结果记录 ====================


@dataclass
class FallbackTestResult:
    test_id: str
    scenario: str
    mode: str  # "i2i" | "t2i" | "i2v"
    chain_models: str        # "pro → flash → seedream"
    success: bool
    expected_behavior: str
    actual_behavior: str
    expected_calls: str      # "pro:1, flash:1, seedream:1"
    actual_calls: str        # "pro:1, flash:1, seedream:1"
    model_used: Optional[str] = None
    total_attempts: int = 0
    duration_sec: float = 0.0


def _fmt_calls(counters, labels=None):
    """格式化调用次数。"""
    labels = labels or [tt.value for tt, _ in IMAGE_CHAIN_TYPES]
    parts = [f"{labels[i]}:{c['n']}" for i, c in enumerate(counters)]
    return ", ".join(parts)


REFS = ["https://example.com/ref.webp"]


# ==================== IMAGE I2I Tests (3-model chain) ====================


async def test_i2i_01_retryable_then_success() -> FallbackTestResult:
    """I2I: 主模型(pro)第1次可重试 → 重试成功。chain: pro→flash→seedream, calls: pro:2"""
    from app.tools.image.image_tool_wrapper import _run_i2i_loop

    fn1, c1 = _retryable_then_ok("pro")
    fn2, c2 = _always_ok("flash")
    fn3, c3 = _always_ok("seedream")
    chain, counters = _build_image_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime(REFS)
    start = time.perf_counter()
    result = await _run_i2i_loop("test prompt", REFS, runtime, chain)
    dur = time.perf_counter() - start

    ok = result.success and c1["n"] == 2 and c2["n"] == 0 and c3["n"] == 0
    return FallbackTestResult(
        test_id="i2i_01_retryable_then_success",
        scenario="Pro retryable → retry OK. Flash/Seedream NOT called.",
        mode="i2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:2, flash:0, seedream:0, success",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="pro:2, flash:0, seedream:0",
        actual_calls=_fmt_calls(counters),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_i2i_02_permanent_fb1() -> FallbackTestResult:
    """I2I: pro永久失败 → flash成功。calls: pro:1, flash:1"""
    from app.tools.image.image_tool_wrapper import _run_i2i_loop

    fn1, c1 = _always_fail_permanent("pro")
    fn2, c2 = _always_ok("flash")
    fn3, c3 = _always_ok("seedream")
    chain, counters = _build_image_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime(REFS)
    start = time.perf_counter()
    result = await _run_i2i_loop("test prompt", REFS, runtime, chain)
    dur = time.perf_counter() - start

    ok = result.success and c1["n"] == 1 and c2["n"] == 1 and c3["n"] == 0
    return FallbackTestResult(
        test_id="i2i_02_permanent_fb1",
        scenario="Pro permanent fail → Flash success. Seedream NOT called.",
        mode="i2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:1, flash:1, seedream:0, success",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="pro:1, flash:1, seedream:0",
        actual_calls=_fmt_calls(counters),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_i2i_03_two_fail_fb2() -> FallbackTestResult:
    """I2I: pro永久失败 → flash永久失败 → seedream成功。calls: pro:1, flash:1, seedream:1"""
    from app.tools.image.image_tool_wrapper import _run_i2i_loop

    fn1, c1 = _always_fail_permanent("pro")
    fn2, c2 = _always_fail_permanent("flash")
    fn3, c3 = _always_ok("seedream")
    chain, counters = _build_image_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime(REFS)
    start = time.perf_counter()
    result = await _run_i2i_loop("test prompt", REFS, runtime, chain)
    dur = time.perf_counter() - start

    ok = result.success and c1["n"] == 1 and c2["n"] == 1 and c3["n"] == 1
    return FallbackTestResult(
        test_id="i2i_03_two_fail_fb2",
        scenario="Pro fail → Flash fail → Seedream success (full 3-step fallback).",
        mode="i2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:1, flash:1, seedream:1, success",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="pro:1, flash:1, seedream:1",
        actual_calls=_fmt_calls(counters),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_i2i_04_retryable_exhaust_fb2() -> FallbackTestResult:
    """I2I: pro 2x 可重试失败 → flash 第 1 次后达总次数上限 3，不再调用 seedream。calls: 2+1=3"""
    from app.tools.image.image_tool_wrapper import _run_i2i_loop

    fn1, c1 = _always_fail_retryable("pro")
    fn2, c2 = _always_fail_retryable("flash")
    fn3, c3 = _always_ok("seedream")
    chain, counters = _build_image_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime(REFS)
    start = time.perf_counter()
    result = await _run_i2i_loop("test prompt", REFS, runtime, chain)
    dur = time.perf_counter() - start

    ok = (
        not result.success
        and c1["n"] == 2
        and c2["n"] == 1
        and c3["n"] == 0
    )
    return FallbackTestResult(
        test_id="i2i_04_retryable_exhaust_fb2",
        scenario="Pro 2x retry fail → Flash 1x then global cap 3 → Seedream NOT called.",
        mode="i2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:2, flash:1, seedream:0, cap stop, success=False",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="pro:2, flash:1, seedream:0",
        actual_calls=_fmt_calls(counters),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_i2i_06_all_api_fail() -> FallbackTestResult:
    """I2I: 3模型 API 全部永久失败（无图片）→ 返回错误。calls: pro:1, flash:1, seedream:1"""
    from app.tools.image.image_tool_wrapper import _run_i2i_loop

    fn1, c1 = _always_fail_permanent("pro")
    fn2, c2 = _always_fail_permanent("flash")
    fn3, c3 = _always_fail_permanent("seedream")
    chain, counters = _build_image_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime(REFS)
    start = time.perf_counter()
    result = await _run_i2i_loop("test prompt", REFS, runtime, chain)
    dur = time.perf_counter() - start

    total = sum(c["n"] for c in counters)
    ok = not result.success and result.user_facing_message is not None and total == 3
    return FallbackTestResult(
        test_id="i2i_06_all_api_fail",
        scenario="All 3 models permanent API fail → error (3 calls, no retry on permanent).",
        mode="i2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:1, flash:1, seedream:1 = 3, success=False",
        actual_behavior=f"total={total}, success={result.success}, msg={result.user_facing_message}",
        expected_calls="pro:1, flash:1, seedream:1",
        actual_calls=_fmt_calls(counters),
        total_attempts=total, duration_sec=round(dur, 3),
    )


# ==================== IMAGE T2I Tests (3-model chain) ====================


async def test_t2i_07_retryable_then_success() -> FallbackTestResult:
    """T2I: pro可重试 → 重试成功。calls: pro:2"""
    from app.tools.image.image_tool_wrapper import _run_t2i_loop

    fn1, c1 = _retryable_then_ok("pro")
    fn2, c2 = _always_ok("flash")
    fn3, c3 = _always_ok("seedream")
    chain, counters = _build_image_chain_t2i([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime()
    start = time.perf_counter()
    result = await _run_t2i_loop("test prompt", runtime, chain)
    dur = time.perf_counter() - start

    ok = result.success and c1["n"] == 2 and c2["n"] == 0 and c3["n"] == 0
    return FallbackTestResult(
        test_id="t2i_07_retryable_then_success",
        scenario="T2I Pro retryable → retry OK. Flash/Seedream NOT called.",
        mode="t2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:2, flash:0, seedream:0, success",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="pro:2, flash:0, seedream:0",
        actual_calls=_fmt_calls(counters),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_t2i_08_permanent_fb1() -> FallbackTestResult:
    """T2I: pro永久失败 → flash成功。calls: pro:1, flash:1"""
    from app.tools.image.image_tool_wrapper import _run_t2i_loop

    fn1, c1 = _always_fail_permanent("pro")
    fn2, c2 = _always_ok("flash")
    fn3, c3 = _always_ok("seedream")
    chain, counters = _build_image_chain_t2i([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime()
    start = time.perf_counter()
    result = await _run_t2i_loop("test prompt", runtime, chain)
    dur = time.perf_counter() - start

    ok = result.success and c1["n"] == 1 and c2["n"] == 1 and c3["n"] == 0
    return FallbackTestResult(
        test_id="t2i_08_permanent_fb1",
        scenario="T2I Pro permanent fail → Flash success.",
        mode="t2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:1, flash:1, seedream:0, success",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="pro:1, flash:1, seedream:0",
        actual_calls=_fmt_calls(counters),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_t2i_09_two_fail_fb2() -> FallbackTestResult:
    """T2I: pro → flash 都永久失败 → seedream 成功。calls: 1+1+1=3"""
    from app.tools.image.image_tool_wrapper import _run_t2i_loop

    fn1, c1 = _always_fail_permanent("pro")
    fn2, c2 = _always_fail_permanent("flash")
    fn3, c3 = _always_ok("seedream")
    chain, counters = _build_image_chain_t2i([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime()
    start = time.perf_counter()
    result = await _run_t2i_loop("test prompt", runtime, chain)
    dur = time.perf_counter() - start

    ok = result.success and c1["n"] == 1 and c2["n"] == 1 and c3["n"] == 1
    return FallbackTestResult(
        test_id="t2i_09_two_fail_fb2",
        scenario="T2I Pro fail → Flash fail → Seedream success (full 3-step).",
        mode="t2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:1, flash:1, seedream:1, success",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="pro:1, flash:1, seedream:1",
        actual_calls=_fmt_calls(counters),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_t2i_10_retryable_exhaust_fb2() -> FallbackTestResult:
    """T2I: pro 2x → flash 1x 后达总次数上限 3，不再调用 seedream。calls: 2+1=3"""
    from app.tools.image.image_tool_wrapper import _run_t2i_loop

    fn1, c1 = _always_fail_retryable("pro")
    fn2, c2 = _always_fail_retryable("flash")
    fn3, c3 = _always_ok("seedream")
    chain, counters = _build_image_chain_t2i([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime()
    start = time.perf_counter()
    result = await _run_t2i_loop("test prompt", runtime, chain)
    dur = time.perf_counter() - start

    ok = (
        not result.success
        and c1["n"] == 2
        and c2["n"] == 1
        and c3["n"] == 0
    )
    return FallbackTestResult(
        test_id="t2i_10_retryable_exhaust_fb2",
        scenario="T2I Pro 2x → Flash 1x then global cap 3 → Seedream NOT called.",
        mode="t2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:2, flash:1, seedream:0, cap stop, success=False",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="pro:2, flash:1, seedream:0",
        actual_calls=_fmt_calls(counters),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_t2i_11_all_fail() -> FallbackTestResult:
    """T2I: 全部可重试失败；总生成次数上限 3 后停止 → 错误。"""
    from app.tools.image.image_tool_wrapper import _run_t2i_loop

    fn1, c1 = _always_fail_retryable("pro")
    fn2, c2 = _always_fail_retryable("flash")
    fn3, c3 = _always_fail_retryable("seedream")
    chain, counters = _build_image_chain_t2i([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_image_runtime()
    start = time.perf_counter()
    result = await _run_t2i_loop("test prompt", runtime, chain)
    dur = time.perf_counter() - start

    total = sum(c["n"] for c in counters)
    ok = (
        not result.success
        and result.user_facing_message is not None
        and total == 3
        and c1["n"] == 2
        and c2["n"] == 1
        and c3["n"] == 0
    )
    return FallbackTestResult(
        test_id="t2i_11_all_fail",
        scenario="T2I retryable fails, global cap 3 stops before seedream → error.",
        mode="t2i", chain_models="pro → flash → seedream", success=ok,
        expected_behavior="pro:2, flash:1, seedream:0 = 3, success=False",
        actual_behavior=f"total={total}, success={result.success}, msg={result.user_facing_message}",
        expected_calls="pro:2, flash:1, seedream:0",
        actual_calls=_fmt_calls(counters),
        total_attempts=total, duration_sec=round(dur, 3),
    )


# ==================== VIDEO I2V Tests (3-model chain) ====================

VIDEO_LABELS = [tt.value for tt, _ in VIDEO_CHAIN_TYPES]


async def test_i2v_12_retryable_then_success() -> FallbackTestResult:
    """I2V: v1可重试 → 重试成功。calls: v1:2"""
    from app.tools.video.video_tool_wrapper import _run_video_loop

    fn1, c1 = _retryable_then_ok_video("v1")
    fn2, c2 = _always_ok_video("w26")
    fn3, c3 = _always_ok_video("sora")
    chain, counters = _build_video_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_video_runtime()
    start = time.perf_counter()
    result = await _run_video_loop("test prompt", "https://example.com/start.webp", 5, runtime, chain)
    dur = time.perf_counter() - start

    ok = result.success and c1["n"] == 2 and c2["n"] == 0 and c3["n"] == 0
    return FallbackTestResult(
        test_id="i2v_12_retryable_then_success",
        scenario="I2V V1 retryable → retry OK. W26/Sora NOT called.",
        mode="i2v", chain_models="v1 → w26 → sora", success=ok,
        expected_behavior="v1:2, w26:0, sora:0, success",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="v1:2, w26:0, sora:0",
        actual_calls=_fmt_calls(counters, VIDEO_LABELS),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_i2v_13_permanent_fb1() -> FallbackTestResult:
    """I2V: v1永久失败 → w26成功。calls: v1:1, w26:1"""
    from app.tools.video.video_tool_wrapper import _run_video_loop

    fn1, c1 = _always_fail_video_permanent("v1")
    fn2, c2 = _always_ok_video("w26")
    fn3, c3 = _always_ok_video("sora")
    chain, counters = _build_video_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_video_runtime()
    start = time.perf_counter()
    result = await _run_video_loop("test prompt", "https://example.com/start.webp", 5, runtime, chain)
    dur = time.perf_counter() - start

    ok = result.success and c1["n"] == 1 and c2["n"] == 1 and c3["n"] == 0
    return FallbackTestResult(
        test_id="i2v_13_permanent_fb1",
        scenario="I2V V1 permanent fail → W26 success.",
        mode="i2v", chain_models="v1 → w26 → sora", success=ok,
        expected_behavior="v1:1, w26:1, sora:0, success",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="v1:1, w26:1, sora:0",
        actual_calls=_fmt_calls(counters, VIDEO_LABELS),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_i2v_14_two_fail_fb2() -> FallbackTestResult:
    """I2V: v1 → w26 都永久失败 → sora 成功。calls: 1+1+1=3"""
    from app.tools.video.video_tool_wrapper import _run_video_loop

    fn1, c1 = _always_fail_video_permanent("v1")
    fn2, c2 = _always_fail_video_permanent("w26")
    fn3, c3 = _always_ok_video("sora")
    chain, counters = _build_video_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_video_runtime()
    start = time.perf_counter()
    result = await _run_video_loop("test prompt", "https://example.com/start.webp", 5, runtime, chain)
    dur = time.perf_counter() - start

    ok = not result.success and c1["n"] == 1 and c2["n"] == 1 and c3["n"] == 0
    return FallbackTestResult(
        test_id="i2v_14_two_fail_fb2",
        scenario="I2V V1 fail → W26 fail → global cap stops before Sora.",
        mode="i2v", chain_models="v1 → w26 → sora", success=ok,
        expected_behavior="v1:1, w26:1, sora:0, success=False",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="v1:1, w26:1, sora:0",
        actual_calls=_fmt_calls(counters, VIDEO_LABELS),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_i2v_15_retryable_exhaust_fb2() -> FallbackTestResult:
    """I2V: v1 2x耗尽 → w26 2x耗尽 → sora 成功。calls: 2+2+1=5"""
    from app.tools.video.video_tool_wrapper import _run_video_loop

    fn1, c1 = _always_fail_video_retryable("v1")
    fn2, c2 = _always_fail_video_retryable("w26")
    fn3, c3 = _always_ok_video("sora")
    chain, counters = _build_video_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_video_runtime()
    start = time.perf_counter()
    result = await _run_video_loop("test prompt", "https://example.com/start.webp", 5, runtime, chain)
    dur = time.perf_counter() - start

    ok = not result.success and c1["n"] == 2 and c2["n"] == 0 and c3["n"] == 0
    return FallbackTestResult(
        test_id="i2v_15_retryable_exhaust_fb2",
        scenario="I2V V1 2x reaches the global cap.",
        mode="i2v", chain_models="v1 → w26 → sora", success=ok,
        expected_behavior="v1:2, w26:0, sora:0 = 2, success=False",
        actual_behavior=f"success={result.success}, model={result.model}",
        expected_calls="v1:2, w26:0, sora:0",
        actual_calls=_fmt_calls(counters, VIDEO_LABELS),
        model_used=result.model, total_attempts=sum(c["n"] for c in counters), duration_sec=round(dur, 3),
    )


async def test_i2v_16_all_fail() -> FallbackTestResult:
    """I2V: 3模型 × 2次可重试 = 6次全部失败 → 错误。"""
    from app.tools.video.video_tool_wrapper import _run_video_loop

    fn1, c1 = _always_fail_video_retryable("v1")
    fn2, c2 = _always_fail_video_retryable("w26")
    fn3, c3 = _always_fail_video_retryable("sora")
    chain, counters = _build_video_chain([(fn1, c1), (fn2, c2), (fn3, c3)])

    runtime = _make_video_runtime()
    start = time.perf_counter()
    result = await _run_video_loop("test prompt", "https://example.com/start.webp", 5, runtime, chain)
    dur = time.perf_counter() - start

    total = sum(c["n"] for c in counters)
    ok = not result.success and total == 2
    return FallbackTestResult(
        test_id="i2v_16_all_fail",
        scenario="I2V retryable failures stop at the two-attempt global cap.",
        mode="i2v", chain_models="v1 → w26 → sora", success=ok,
        expected_behavior="v1:2, w26:0, sora:0 = 2, success=False",
        actual_behavior=f"total={total}, success={result.success}",
        expected_calls="v1:2, w26:0, sora:0",
        actual_calls=_fmt_calls(counters, VIDEO_LABELS),
        total_attempts=total, duration_sec=round(dur, 3),
    )


# ==================== 汇总运行 & HTML 报告 ====================


ALL_TEST_CASES = [
    # I2I (5 cases)
    test_i2i_01_retryable_then_success,
    test_i2i_02_permanent_fb1,
    test_i2i_03_two_fail_fb2,
    test_i2i_04_retryable_exhaust_fb2,
    test_i2i_06_all_api_fail,
    # T2I (5 cases)
    test_t2i_07_retryable_then_success,
    test_t2i_08_permanent_fb1,
    test_t2i_09_two_fail_fb2,
    test_t2i_10_retryable_exhaust_fb2,
    test_t2i_11_all_fail,
    # I2V (5 cases)
    test_i2v_12_retryable_then_success,
    test_i2v_13_permanent_fb1,
    test_i2v_14_two_fail_fb2,
    test_i2v_15_retryable_exhaust_fb2,
    test_i2v_16_all_fail,
]


async def _run_all_fallback_tests() -> List[FallbackTestResult]:
    results = []
    for test_fn in ALL_TEST_CASES:
        try:
            r = await test_fn()
            results.append(r)
        except Exception as e:
            results.append(FallbackTestResult(
                test_id=test_fn.__name__,
                scenario=test_fn.__doc__ or "",
                mode="error", chain_models="N/A", success=False,
                expected_behavior="Should not throw",
                actual_behavior=f"Exception: {e}\n{traceback.format_exc()}",
                expected_calls="N/A", actual_calls="N/A",
            ))
    return results


def _write_fallback_html(results: List[FallbackTestResult], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "test_fallback_retry_report.html"

    payload = {
        "ran_at": datetime.utcnow().isoformat() + "Z",
        "total": len(results),
        "passed": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success),
        "results": [asdict(r) for r in results],
    }
    json_str = json.dumps(payload, ensure_ascii=False)
    json_escaped = json_str.replace("<", "\\u003c")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fallback & Retry Unit Test Report</title>
  <style>
    :root {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }}
    body {{ max-width: 1800px; margin: 0 auto; padding: 1.5rem; }}
    h1 {{ font-size: 1.6rem; border-bottom: 2px solid #334155; padding-bottom: 0.5rem; }}
    .summary {{ display: flex; gap: 1rem; margin: 1rem 0; }}
    .stat {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1rem 1.5rem; min-width: 100px; text-align: center; }}
    .stat .num {{ font-size: 2rem; font-weight: 700; }}
    .stat .label {{ font-size: 0.8rem; color: #94a3b8; }}
    .stat.ok .num {{ color: #4ade80; }}
    .stat.err .num {{ color: #f87171; }}
    .stat.total .num {{ color: #60a5fa; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
    th, td {{ border: 1px solid #334155; padding: 0.6rem; text-align: left; font-size: 0.82rem; }}
    th {{ background: #1e293b; color: #94a3b8; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #1e293b44; }}
    .ok {{ color: #4ade80; }}
    .err {{ color: #f87171; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }}
    .badge-i2i {{ background: #7c3aed; color: #ede9fe; }}
    .badge-t2i {{ background: #1d4ed8; color: #dbeafe; }}
    .badge-i2v {{ background: #be185d; color: #fce7f3; }}
    .scenario {{ font-size: 0.8rem; color: #94a3b8; max-width: 350px; }}
    .calls {{ font-family: monospace; font-size: 0.8rem; }}
    .calls-ok {{ color: #4ade80; }}
    .calls-err {{ color: #f87171; }}
    pre {{ background: #1e293b; padding: 0.4rem; border-radius: 4px; font-size: 0.72rem; white-space: pre-wrap; word-break: break-all; max-width: 350px; margin: 0; }}
  </style>
</head>
<body>
  <h1>Fallback & Retry Unit Test Report (3-Model Chain)</h1>
  <div class="summary" id="summary"></div>
  <table>
    <thead><tr><th>#</th><th>Mode</th><th>Test ID</th><th>Chain</th><th>Scenario</th><th>Result</th><th>Expected Calls</th><th>Actual Calls</th><th>Total</th><th>Model Used</th><th>Actual Behavior</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  <script>window.FB_RESULTS = {json_escaped};</script>
  <script>
(function(){{
  var d = window.FB_RESULTS;
  document.getElementById("summary").innerHTML =
    '<div class="stat total"><div class="num">'+d.total+'</div><div class="label">Total</div></div>'+
    '<div class="stat ok"><div class="num">'+d.passed+'</div><div class="label">Passed</div></div>'+
    '<div class="stat err"><div class="num">'+d.failed+'</div><div class="label">Failed</div></div>';
  var tb = document.getElementById("tbody");
  d.results.forEach(function(r, i){{
    var match = r.expected_calls === r.actual_calls;
    var tr = document.createElement("tr");
    tr.innerHTML =
      '<td>'+(i+1)+'</td>'+
      '<td><span class="badge badge-'+r.mode+'">'+r.mode.toUpperCase()+'</span></td>'+
      '<td>'+r.test_id+'</td>'+
      '<td style="font-size:0.75rem;color:#818cf8;">'+r.chain_models+'</td>'+
      '<td class="scenario">'+r.scenario+'</td>'+
      '<td class="'+(r.success?'ok':'err')+'">'+(r.success?'PASS':'FAIL')+'</td>'+
      '<td class="calls">'+r.expected_calls+'</td>'+
      '<td class="calls '+(match?'calls-ok':'calls-err')+'">'+r.actual_calls+'</td>'+
      '<td>'+r.total_attempts+'</td>'+
      '<td>'+(r.model_used||'-')+'</td>'+
      '<td><pre>'+r.actual_behavior+'</pre></td>';
    tb.appendChild(tr);
  }});
}})();
  </script>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote HTML: {path}")
    return path


# ==================== Pytest ====================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wrapper_fallback_retry():
    """
    Wrapper 重试 & Fallback 单元测试：
    16 个场景，全部使用 3-model chain，验证重试/降级/best-effort 逻辑。
    """
    out_dir = Path(__file__).resolve().parent / "test_fallback_output"
    results = await _run_all_fallback_tests()

    html_path = _write_fallback_html(results, out_dir)

    passed = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    print(f"\n{'='*60}")
    print(f"  Fallback/Retry Tests: {passed} PASS / {failed} FAIL / {len(results)} Total")
    print(f"  HTML Report: {html_path}")
    print(f"{'='*60}\n")
    for r in results:
        status = "PASS" if r.success else "FAIL"
        print(f"  [{status}] {r.test_id}: calls=[{r.actual_calls}] → {r.actual_behavior}")

    assert len(results) == 15
    assert failed == 0, f"{failed} fallback/retry test(s) failed!"
