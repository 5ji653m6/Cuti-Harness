#!/usr/bin/env python3
"""
单独运行看 I2I ainvoke 返回格式（不依赖 pytest）。
cd Cuti-VideoAgent && python tests/tools/script_check_i2i_return.py
"""
import asyncio
from types import SimpleNamespace

from app.models.tool_enums import ToolMode
from app.models.user_options import UserOption
from app.services.tool_service import ToolService
from app.tools.context_schemas import ImageGenerationContext
from app.models.image_result import ImageGenerationResult
from app.tools.image import image_tool_wrapper


async def main():
    fixed_result = ImageGenerationResult(
        success=True,
        image_url="https://example.com/fake.webp",
        message="mock",
    )

    async def _mock_run_i2i_loop(*args, **kwargs):
        return fixed_result

    image_tool_wrapper._run_i2i_loop = _mock_run_i2i_loop

    user_option = UserOption.default()
    tools_info = ToolService.get_image_generation_tools(user_option=user_option, mode=ToolMode.I2I)
    i2i_tool = tools_info.primary_tool
    assert i2i_tool is not None

    ctx = ImageGenerationContext(reference_image_urls=["https://example.com/ref.webp"])
    runtime = SimpleNamespace(context=ctx)
    out = await i2i_tool.ainvoke(
        {
            "prompt": "test",
            "reference_image_urls": ["https://example.com/ref.webp"],
            "runtime": runtime,
        },
        config={"metadata": {"consistency_run_id": "test"}},
    )

    print("--- I2I ainvoke 返回 ---")
    print("type(out) =", type(out).__name__)
    print("isinstance(out, (list, tuple)) =", isinstance(out, (list, tuple)))
    if isinstance(out, (list, tuple)):
        print("len(out) =", len(out))
        for i, x in enumerate(out):
            print(f"  out[{i}] type =", type(x).__name__)
            if hasattr(x, "success"):
                print(f"  out[{i}].success =", x.success)
    else:
        print("hasattr(out, 'success') =", hasattr(out, "success"))
        print("hasattr(out, 'artifact') =", hasattr(out, "artifact"))
        if hasattr(out, "artifact"):
            a = out.artifact
            print("  out.artifact type =", type(a).__name__)
            print("  hasattr(out.artifact, 'success') =", hasattr(a, "success"))
        if hasattr(out, "success"):
            print("out.success =", out.success)
    print("---")


if __name__ == "__main__":
    asyncio.run(main())
