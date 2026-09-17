from __future__ import annotations

import pytest

from app.tools.runtime import ToolRuntime, tool


@pytest.mark.asyncio
async def test_async_tool_keeps_metadata_and_invokes_with_explicit_runtime() -> None:
    @tool("sample.generate")
    async def sample(*, prompt: str, runtime: ToolRuntime[str]) -> str:
        """Generate one sample."""
        return f"{runtime.context}:{prompt}"

    assert sample.name == "sample.generate"
    assert sample.description == "Generate one sample."
    assert sample.coroutine is not None
    assert await sample.ainvoke(
        {"prompt": "hello", "runtime": ToolRuntime(context="ctx")}
    ) == "ctx:hello"
