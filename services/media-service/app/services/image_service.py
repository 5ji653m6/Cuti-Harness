import asyncio
import logging
from io import BytesIO
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


async def get_image_info(file_path: str) -> dict:
    def _info():
        with Image.open(file_path) as img:
            return {"width": img.width, "height": img.height}
    return await asyncio.to_thread(_info)


async def resize_image(
    input_path: str,
    output_path: str,
    target_width: int,
    target_height: int,
    fmt: str = "webp",
    quality: int = 85,
) -> dict:
    def _resize():
        with Image.open(input_path) as img:
            if img.mode == "RGBA" and fmt.lower() != "png":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1])
                img = bg
            elif img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            resized.save(output_path, fmt.upper(), quality=quality)
            return {"width": resized.width, "height": resized.height}
    return await asyncio.to_thread(_resize)
