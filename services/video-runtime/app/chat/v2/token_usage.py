from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Awaitable, Callable

from .models import DomainEvent


AttemptAuditor = Callable[[dict[str, Any]], Awaitable[None]]
_attempt_auditor: ContextVar[AttemptAuditor | None] = ContextVar(
    "cuti_v2_llm_attempt_auditor", default=None,
)


@contextmanager
def llm_attempt_audit(auditor: AttemptAuditor):
    token = _attempt_auditor.set(auditor)
    try:
        yield
    finally:
        _attempt_auditor.reset(token)


async def audit_llm_attempt(**payload: Any) -> None:
    auditor = _attempt_auditor.get()
    if auditor is not None:
        await auditor(payload)


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _usage_from_response(response: Any) -> dict[str, int]:
    generations = getattr(response, "generations", None) or []
    message = None
    if generations and generations[0]:
        message = getattr(generations[0][0], "message", None)
    usage = getattr(message, "usage_metadata", None) or {}
    response_metadata = getattr(message, "response_metadata", None) or {}
    raw = (
        response_metadata.get("token_usage")
        or response_metadata.get("usage")
        or getattr(response, "llm_output", None)
        or {}
    )
    if isinstance(raw, dict) and isinstance(raw.get("token_usage"), dict):
        raw = raw["token_usage"]
    input_tokens = _int(usage.get("input_tokens") or raw.get("prompt_tokens") or raw.get("input_tokens"))
    output_tokens = _int(usage.get("output_tokens") or raw.get("completion_tokens") or raw.get("output_tokens"))
    details = usage.get("input_token_details") or raw.get("prompt_tokens_details") or {}
    output_details = usage.get("output_token_details") or raw.get("completion_tokens_details") or {}
    cached_tokens = _int(details.get("cache_read") or details.get("cached_tokens"))
    reasoning_tokens = _int(output_details.get("reasoning") or output_details.get("reasoning_tokens"))
    audio_input_tokens = _int(details.get("audio") or details.get("audio_tokens"))
    total_tokens = _int(usage.get("total_tokens") or raw.get("total_tokens"))
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "reasoning_tokens": reasoning_tokens,
        "audio_input_tokens": audio_input_tokens,
        "total_tokens": total_tokens,
    }


def _requested_tokens(error: BaseException) -> int:
    match = re.search(r"requested\s+([0-9][0-9,]*)", str(error), re.IGNORECASE)
    return int(match.group(1).replace(",", "")) if match else 0


class V2TokenUsageCallback:
    """Persist one auditable event for every V2 LLM request and result."""

    def __init__(self, repo: Any, *, run_id: str, scope: str, task_id: str | None = None,
                 capability_id: str | None = None, attempt: int | None = None) -> None:
        self.repo = repo
        self.v2_run_id = run_id
        self.scope = scope
        self.task_id = task_id
        self.capability_id = capability_id
        self.attempt = attempt
        self.started: dict[str, tuple[float, dict[str, Any]]] = {}

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        await self.repo.append_event(DomainEvent(
            run_id=self.v2_run_id,
            type=event_type,
            payload={
                "scope": self.scope,
                "task_id": self.task_id,
                "capability_id": self.capability_id,
                "attempt": self.attempt,
                **payload,
            },
        ))

    async def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], *,
                                  run_id: Any, parent_run_id: Any = None, tags=None,
                                  metadata=None, **kwargs: Any) -> None:
        call_id = str(run_id)
        model = str(
            (metadata or {}).get("ls_model_name")
            or serialized.get("kwargs", {}).get("model_name")
            or serialized.get("kwargs", {}).get("model")
            or "unknown"
        )
        message_count = sum(len(batch) for batch in messages or [])
        character_count = sum(
            len(str(getattr(message, "content", "")))
            for batch in messages or [] for message in batch
        )
        info = {
            "llm_call_id": call_id,
            "parent_call_id": str(parent_run_id) if parent_run_id else None,
            "provider": "openai" if "gpt" in model.lower() else "unknown",
            "model": model,
            "message_count": message_count,
            "input_characters": character_count,
            "started_at": datetime.now(UTC).isoformat(),
        }
        self.started[call_id] = (monotonic(), info)
        await self._emit("llm.request.started", info)

    async def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        call_id = str(run_id)
        started_at, info = self.started.pop(call_id, (monotonic(), {"llm_call_id": call_id}))
        generations = getattr(response, "generations", None) or []
        message = getattr(generations[0][0], "message", None) if generations and generations[0] else None
        metadata = getattr(message, "response_metadata", None) or {}
        await self._emit("llm.usage", {
            **info,
            **_usage_from_response(response),
            "status": "succeeded",
            "key_slot": metadata.get("cuti_key_slot", "primary"),
            "duration_ms": round((monotonic() - started_at) * 1000),
            "usage_reported": True,
        })

    async def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        call_id = str(run_id)
        started_at, info = self.started.pop(call_id, (monotonic(), {"llm_call_id": call_id}))
        await self._emit("llm.usage", {
            **info,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
            "audio_input_tokens": 0,
            "total_tokens": 0,
            "requested_tokens": _requested_tokens(error),
            "status": "failed",
            "usage_reported": False,
            "error_type": type(error).__name__,
            "error": str(error)[:2000],
            "duration_ms": round((monotonic() - started_at) * 1000),
        })

    async def audit_attempt(self, payload: dict[str, Any]) -> None:
        await self._emit("llm.attempt", {
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        })


def summarize_usage(events: list[DomainEvent]) -> dict[str, Any]:
    usage = [event.payload for event in events if event.type == "llm.usage"]
    attempts = [event.payload for event in events if event.type == "llm.attempt"]
    totals = {
        key: sum(_int(item.get(key)) for item in usage)
        for key in (
            "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens",
            "audio_input_tokens", "total_tokens", "requested_tokens",
        )
    }
    by_scope: dict[str, dict[str, int]] = {}
    by_task: dict[str, dict[str, Any]] = {}
    for item in usage:
        scope = str(item.get("scope") or "unknown")
        bucket = by_scope.setdefault(scope, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
        bucket["calls"] += 1
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            bucket[key] += _int(item.get(key))
        task_id = item.get("task_id")
        if task_id:
            task = by_task.setdefault(str(task_id), {
                "task_id": task_id, "capability_id": item.get("capability_id"),
                "calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            })
            task["calls"] += 1
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                task[key] += _int(item.get(key))
    return {
        **totals,
        "calls": len(usage),
        "failed_calls": sum(1 for item in usage if item.get("status") == "failed"),
        "retry_attempts": len(attempts),
        "by_scope": by_scope,
        "by_task": list(by_task.values()),
        "records": usage,
        "attempt_records": attempts,
    }
