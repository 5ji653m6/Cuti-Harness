"""Direct OpenAI text generation with one-key failover."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from openai import AsyncOpenAI


def _retry_delay(exc: BaseException, retry_number: int, maximum: float) -> float:
    match = re.search(
        r"try again in\s+([0-9]+(?:\.[0-9]+)?)\s*(ms|s)",
        str(exc).lower(),
    )
    if match:
        delay = float(match.group(1)) / (1000.0 if match.group(2) == "ms" else 1.0)
        delay += 0.1
    else:
        delay = float(2 ** (retry_number - 1))
    return min(max(delay, 0.1), maximum)


def _is_rate_limit_error(exc: BaseException) -> bool:
    return type(exc).__name__ == "RateLimitError" or "rate limit" in str(exc).lower()


async def _request(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    content: Any,
    timeout: float,
    key_slot: str,
    max_rate_limit_retries: int,
    max_rate_limit_delay: float,
) -> str:
    from app.chat.v2.token_usage import audit_llm_attempt

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url or None,
        timeout=timeout,
    )
    retries = 0
    while True:
        try:
            await audit_llm_attempt(
                key_slot=key_slot,
                attempt=retries + 1,
                status="started",
            )
            if model.startswith("gpt-5"):
                response_content = content
                if isinstance(content, list):
                    response_content = [
                        (
                            {"type": "input_text", "text": block.get("text", "")}
                            if block.get("type") == "text"
                            else {
                                "type": "input_image",
                                "image_url": block.get("image_url", {}).get("url", ""),
                            }
                        )
                        for block in content
                        if isinstance(block, dict)
                    ]
                response = await client.responses.create(
                    model=model,
                    input=[{"role": "user", "content": response_content}],
                )
                text = response.output_text or ""
            else:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    temperature=0,
                )
                text = response.choices[0].message.content or ""
            usage = response.usage
            await audit_llm_attempt(
                key_slot=key_slot,
                attempt=retries + 1,
                status="succeeded",
                input_tokens=(
                    getattr(usage, "prompt_tokens", None)
                    or getattr(usage, "input_tokens", 0)
                    or 0
                ),
                output_tokens=(
                    getattr(usage, "completion_tokens", None)
                    or getattr(usage, "output_tokens", 0)
                    or 0
                ),
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
            )
            return text
        except BaseException as exc:
            if (
                isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit))
                or not _is_rate_limit_error(exc)
                or retries >= max_rate_limit_retries
            ):
                await audit_llm_attempt(
                    key_slot=key_slot,
                    attempt=retries + 1,
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:1000],
                )
                raise
            retries += 1
            delay = _retry_delay(exc, retries, max_rate_limit_delay)
            await audit_llm_attempt(
                key_slot=key_slot,
                attempt=retries,
                status="retry_scheduled",
                delay_seconds=delay,
                error_type=type(exc).__name__,
            )
            await asyncio.sleep(delay)


async def generate_openai_text(
    *,
    model: str,
    content: Any,
    api_key: str,
    fallback_api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 120.0,
) -> str:
    """Generate text directly through the OpenAI SDK.

    The primary key gets one request. If it fails before a result is returned,
    a distinct configured backup key retries the same request. Rate limits on
    the backup key use bounded exponential backoff.
    """
    primary = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
    backup = (fallback_api_key or os.getenv("OPENAI_API_KEY_FALLBACK", "")).strip()
    if not primary:
        raise ValueError("OPENAI_API_KEY is required for atomic.text.generate")

    common = {
        "base_url": base_url,
        "model": model,
        "content": content,
        "timeout": timeout,
        "max_rate_limit_retries": max(0, int(os.getenv("OPENAI_RATE_LIMIT_MAX_RETRIES", "3"))),
        "max_rate_limit_delay": max(0.1, float(os.getenv("OPENAI_RATE_LIMIT_MAX_DELAY_SECONDS", "30"))),
    }
    try:
        return await _request(api_key=primary, key_slot="primary", **common)
    except BaseException as exc:
        if (
            isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit))
            or not backup
            or backup == primary
        ):
            raise
        return await _request(api_key=backup, key_slot="fallback", **common)
