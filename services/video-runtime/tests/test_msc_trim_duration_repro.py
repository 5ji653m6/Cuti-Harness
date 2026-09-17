"""
MSC video/trim 时长漂移 — 集成冒烟（默认跳过）。

需同时设置:
  MEDIA_SERVICE_URL
  MSC_TRIM_REPRO_VIDEO_URL   # 一条可公网/CDN 访问的 mp4（口型「trim 前」长片最佳）

运行:
  MSC_TRIM_REPRO_VIDEO_URL='https://...' MEDIA_SERVICE_URL='http://...' \\
    pytest tests/test_msc_trim_duration_repro.py -m integration -s
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_repro_module():
    path = ROOT / "scripts" / "repro_msc_video_trim_drift.py"
    spec = importlib.util.spec_from_file_location("repro_msc_video_trim_drift", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["repro_msc_video_trim_drift"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.integration
@pytest.mark.asyncio
async def test_msc_trim_repro_smoke():
    base = os.environ.get("MEDIA_SERVICE_URL", "").strip().rstrip("/")
    video_url = os.environ.get("MSC_TRIM_REPRO_VIDEO_URL", "").strip()
    if not base or not video_url:
        pytest.skip("需要 MEDIA_SERVICE_URL 与 MSC_TRIM_REPRO_VIDEO_URL")

    target = float(os.environ.get("MSC_TRIM_REPRO_TARGET_SEC", "3.1"))
    mode = os.environ.get("MSC_TRIM_REPRO_MODE", "trim_only")

    mod = _load_repro_module()
    r = await mod.repro_trim_drift(
        base, video_url, target, mode, do_ffprobe=False, verbose=False
    )

    assert r["result_url"]
    assert r["duration_after_msc"] > 0
    # 仅记录漂移，不断言失败（黑盒行为因片源/FPS 而异）
    print(
        f"\n[MSC trim repro] target={r['target']} after={r['duration_after_msc']:.4f} "
        f"delta={r['delta_after_minus_target']:+.4f} mode={r['mode']}\n"
    )
