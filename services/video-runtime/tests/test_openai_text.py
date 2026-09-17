from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.openai_text import generate_openai_text


@pytest.mark.asyncio
async def test_gpt5_uses_responses_api_and_converts_image_blocks(monkeypatch) -> None:
    captured = {}

    class Responses:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_text="done",
                usage=SimpleNamespace(input_tokens=3, output_tokens=1, total_tokens=4),
            )

    class Client:
        def __init__(self, **_kwargs):
            self.responses = Responses()
            self.chat = SimpleNamespace(completions=None)

    monkeypatch.setattr("app.llm.openai_text.AsyncOpenAI", Client)
    result = await generate_openai_text(
        model="gpt-5.6-terra",
        api_key="primary",
        content=[
            {"type": "text", "text": "inspect"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    )

    assert result == "done"
    assert captured["input"][0]["content"][0] == {
        "type": "input_text", "text": "inspect",
    }
    assert captured["input"][0]["content"][1]["type"] == "input_image"


@pytest.mark.asyncio
async def test_failed_primary_retries_with_distinct_backup_key(monkeypatch) -> None:
    used_keys: list[str] = []

    class Completions:
        def __init__(self, api_key: str):
            self.api_key = api_key

        async def create(self, **_kwargs):
            used_keys.append(self.api_key)
            if self.api_key == "primary":
                raise RuntimeError("primary unavailable")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="backup"))],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3),
            )

    class Client:
        def __init__(self, *, api_key: str, **_kwargs):
            self.chat = SimpleNamespace(completions=Completions(api_key))
            self.responses = None

    monkeypatch.setattr("app.llm.openai_text.AsyncOpenAI", Client)
    result = await generate_openai_text(
        model="gpt-4.1-mini",
        api_key="primary",
        fallback_api_key="backup",
        content="hello",
    )

    assert result == "backup"
    assert used_keys == ["primary", "backup"]
