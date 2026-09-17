"""
Common image utilities: downsampling etc., reused by Nano Banana, Seedream, WaveSpeed, etc.
"""
import io
import logging
from typing import Tuple

from PIL import Image

logger = logging.getLogger(__name__)

# when the difference < this threshold, force resize to the target size (slight stretch, visually imperceptible); when >=, keep aspect ratio without stretching, to avoid visible distortion
DOWNSCALE_FORCE_EXACT_THRESHOLD = 0.03  # 3%


def downsample_to_target_sync(image_bytes: bytes, target_width: int, target_height: int) -> Tuple[bytes, dict]:
    """Keyframe downsampling: prefer aligning to standard resolutions, ensuring pipeline consistency and avoiding Assemble black bars and odd/non-standard pixels.

    Strategy (engineering alignment vs mathematical aspect ratio):
    - First scale down proportionally to fit within the target box, giving (new_w, new_h).
    - If the relative difference from target < 3%: force resize to (target_width, target_height), ensuring standard output size (<2% stretch is visually imperceptible).
    - If the difference >= 3%: keep proportional output without stretching (e.g. keep 1344x768 when the 2.5 Flash 1080p original is insufficient).
    Uniformly outputs webp. Called in an executor to avoid blocking.
    Returns (output bytes, metadata) for logs and reports.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    scale = min(target_width / w, target_height / h, 1.0)
    locked = False
    force_exact = False
    out_w, out_h = w, h
    if scale < 1.0:
        new_w = max(1, round(w * scale))
        new_h = max(1, round(h * scale))
        diff_w = abs(new_w - target_width) / target_width if target_width else 0
        diff_h = abs(new_h - target_height) / target_height if target_height else 0
        rel_diff = max(diff_w, diff_h)
        if rel_diff < DOWNSCALE_FORCE_EXACT_THRESHOLD:
            new_w, new_h = target_width, target_height
            force_exact = True
            locked = True
        else:
            locked = False
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        out_w, out_h = new_w, new_h
    meta = {
        "orig_w": w, "orig_h": h,
        "target_w": target_width, "target_h": target_height,
        "scale": scale, "locked": locked, "force_exact": force_exact,
        "out_w": out_w, "out_h": out_h,
    }
    logger.info(
        "下采样: 原图 %dx%d → 目标 %dx%d, scale=%.4f, locked=%s, force_exact=%s → 输出 %dx%d",
        w, h, target_width, target_height, scale, locked, force_exact, out_w, out_h,
    )
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=90)
    return buf.getvalue(), meta
