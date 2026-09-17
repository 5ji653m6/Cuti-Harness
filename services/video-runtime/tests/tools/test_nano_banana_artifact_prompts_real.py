"""
真实集成测试：Nano Banana 2 / 同系列模型 + 易诱发「机顶闪 / 红眼 / 硬闪 / 不自然高光」类画面的 prompt。

这些 prompt 用于**人工**对照：模型是否出现怪异闪光、瞳孔发红/发白、IR 眼反光、过曝脸等。
自动化只断言 API 成功与 URL 非空，**不做像素级红眼检测**。

常见易诱发因素（供写 prompt 时参考）：
- 明确要求 red-eye、on-camera flash、direct flash、paparazzi flash
- 夜店/频闪 + 正面闪灯混合
- 逆光 + 错误补光（mismatched fill flash）
- 红外夜视 / CCTV「眼睛亮点」
- 一次性相机 / 机顶闪过度曝光

运行（需 GOOGLE_API_KEY，消耗额度）：
  cd Cuti-VideoAgent && pytest tests/tools/test_nano_banana_artifact_prompts_real.py -v -m integration

仅跑 catalyst 系列对比（3 次调用）：
  pytest tests/tools/test_nano_banana_artifact_prompts_real.py::test_nano_banana_series_same_catalyst_prompt_all_models -v -m integration

真实跑图 + Gemini 视觉判定「轮廓边缘淡光晕」并写 JSON 报告：
  python scripts/run_nano_banana_halo_probe.py --preset quick
  python scripts/run_nano_banana_halo_probe.py --preset edge
  python scripts/run_nano_banana_halo_probe.py --preset full
  python scripts/run_nano_banana_halo_probe.py --preset nb_nbpro
"""
from __future__ import annotations

import os

import pytest

from app.models.tool_enums import AspectRatio, Resolution, ToolType
from app.tools.image.nano_banana import _generate_image_with_nano_banana


pytestmark = pytest.mark.integration


# (case_id, prompt) — 英文描述，与 Gemini 图像 API 一致
FLASH_REDEYE_STRESS_PROMPTS: list[tuple[str, str]] = [
    (
        "red_eye_direct_flash",
        "Portrait at night outdoors, amateur snapshot, cheap compact camera with direct on-camera flash, "
        "strong classic red-eye effect in both eyes, pupils glowing saturated red, very dark background, "
        "harsh flash falloff on face, realistic photography.",
    ),
    (
        "paparazzi_multi_flash",
        "Celebrity stepping out of a car at night, multiple harsh white camera flashes, strong lens flares, "
        "chaotic paparazzi press style, face partially lit by overlapping flashes, high contrast, cinematic 16:9.",
    ),
    (
        "nightclub_strobe_and_flash",
        "Crowded nightclub dance floor, colored LED strobes plus sudden white on-camera style flash on faces, "
        "sweaty skin, mixed color casts, occasional red-eye glints, grainy high-ISO look, wide shot.",
    ),
    (
        "backlit_wrong_fill_flash",
        "Backlit portrait against bright sunset sky, strong orange rim light, but mismatched cold fill flash "
        "on the face, uneven white balance, overexposed cheekbones, unnatural mix of warm rim and white face light.",
    ),
    (
        "cctv_ir_eye_reflection",
        "Monochrome security camera night vision, slight green tint, grainy CCTV, bright IR reflection in eyes "
        "like two glowing white dots, empty corridor, wide angle, realistic surveillance aesthetic.",
    ),
    (
        "disposable_camera_party_flash",
        "1990s indoor house party, disposable film camera with harsh on-camera flash, overexposed faces in foreground, "
        "deep harsh shadows on wall behind, cheap snapshot look, slight motion blur from movement.",
    ),
]

# 单条「催化剂」prompt：用于同系列多模型并排对比
CATALYST_REDEYE_PROMPT = (
    "Close-up portrait at night, single harsh on-camera flash, explicit red-eye effect with bright red pupils, "
    "dark background, amateur phone photo realism, sharp focus on eyes."
)


def _require_google_key() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not set")


@pytest.mark.parametrize("case_id,prompt", FLASH_REDEYE_STRESS_PROMPTS)
@pytest.mark.asyncio
async def test_nano_banana_2_t2i_flash_artifact_prompts(case_id: str, prompt: str) -> None:
    """Nano Banana 2（Gemini 3.1 Flash Image）：多条易诱发闪光/红眼类问题的 T2I。"""
    _require_google_key()

    result = await _generate_image_with_nano_banana(
        prompt=prompt,
        reference_image_urls=None,
        aspect_ratio=AspectRatio.LANDSCAPE,
        resolution=Resolution.P720,
        model=ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
    )
    assert result.success, f"[{case_id}] {result.error_msg or result.raw_error_msg}"
    assert result.image_url, f"[{case_id}] empty image_url"
    assert result.model == ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW.value
    print(f"\n[{case_id}] NB2 ok → {result.image_url}")


@pytest.mark.parametrize(
    "model",
    [
        ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
        ToolType.GEMINI_3_PRO_IMAGE_PREVIEW,
        ToolType.GEMINI_2_5_FLASH_IMAGE,
    ],
)
@pytest.mark.asyncio
async def test_nano_banana_series_same_catalyst_prompt_all_models(model: ToolType) -> None:
    """同一条红眼/硬闪催化剂 prompt，在 Nano Banana 2 / Pro / Flash 三档各跑一次，便于横向对比。"""
    _require_google_key()

    result = await _generate_image_with_nano_banana(
        prompt=CATALYST_REDEYE_PROMPT,
        reference_image_urls=None,
        aspect_ratio=AspectRatio.LANDSCAPE,
        resolution=Resolution.P720,
        model=model,
    )
    label = model.name
    assert result.success, f"[{label}] {result.error_msg or result.raw_error_msg}"
    assert result.image_url, f"[{label}] empty image_url"
    assert result.model == model.value
    print(f"\n[{label}] catalyst ok → {result.image_url}")
