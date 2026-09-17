"""Integration: Alibaba HappyHorse 1.1 Image-to-Video — 计费单元测试 + 规格脚本入口。

完整 ffprobe 矩阵（分辨率×宽高比×时长、TARGET 对比）请用专用脚本（conda env cuti-video-local）：

  conda run -n cuti-video-local python scripts/test_wavespeed_happyhorse_1_1_i2v_specs.py --seedream

  conda run -n cuti-video-local python scripts/test_wavespeed_happyhorse_1_1_i2v_specs.py --seedream --durations 3 5 15

或 probe 全矩阵：

  conda run -n cuti-video-local python scripts/probe_raw_tool_specs.py --skip-image \\
    --video-tools \"HappyHorse 1.1\" --video-resolutions 480p 720p 1080p --durations 3 5 15 \\
    --parallel 3 --results-json scripts/happyhorse_1_1_specs_results.json \\
    --output-md docs/tool-output-specs_happyhorse_1_1_probe.md

本文件仅跑计费（无需 API Key）：

  conda run -n cuti-video-local pytest tests/tools/test_happyhorse_1_1_i2v_integration.py -k cost -q
"""
import os
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

from app.models.tool_enums import Resolution, ToolType
from app.services.tool_service import ToolService


def test_happyhorse_1_1_i2v_cost_720p_5s():
    cost = ToolService.calculate_cost(
        ToolType.HAPPYHORSE_1_1_I2V, duration=5, resolution=Resolution.P720
    )
    assert cost == pytest.approx(0.70)


def test_happyhorse_1_1_i2v_cost_1080p_5s():
    cost = ToolService.calculate_cost(
        ToolType.HAPPYHORSE_1_1_I2V, duration=5, resolution=Resolution.P1080
    )
    assert cost == pytest.approx(0.945)


def test_happyhorse_1_1_i2v_cost_720p_10s():
    cost = ToolService.calculate_cost(
        ToolType.HAPPYHORSE_1_1_I2V, duration=10, resolution=Resolution.P720
    )
    assert cost == pytest.approx(1.40)


def test_happyhorse_1_1_i2v_cost_480p_bills_as_720p():
    cost = ToolService.calculate_cost(
        ToolType.HAPPYHORSE_1_1_I2V, duration=5, resolution=Resolution.P480
    )
    assert cost == pytest.approx(0.70)
