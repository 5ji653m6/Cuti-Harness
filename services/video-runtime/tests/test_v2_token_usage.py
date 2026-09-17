from types import SimpleNamespace

from app.chat.v2.models import DomainEvent
from app.chat.v2.token_usage import V2TokenUsageCallback, summarize_usage


class Repo:
    def __init__(self):
        self.events = []

    async def append_event(self, event):
        self.events.append(event)
        return event


async def test_callback_persists_exact_usage():
    repo = Repo()
    callback = V2TokenUsageCallback(repo, run_id="run-1", scope="coordinator")
    await callback.on_chat_model_start(
        {"kwargs": {"model": "gpt-5.6"}}, [[SimpleNamespace(content="hello")]],
        run_id="call-1", metadata={"ls_model_name": "gpt-5.6"},
    )
    message = SimpleNamespace(
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 25,
            "total_tokens": 125,
            "input_token_details": {"cache_read": 60},
            "output_token_details": {"reasoning": 10},
        },
        response_metadata={"cuti_key_slot": "fallback"},
    )
    response = SimpleNamespace(generations=[[SimpleNamespace(message=message)]])
    await callback.on_llm_end(response, run_id="call-1")
    summary = summarize_usage(repo.events)
    assert summary["input_tokens"] == 100
    assert summary["output_tokens"] == 25
    assert summary["cached_tokens"] == 60
    assert summary["reasoning_tokens"] == 10
    assert summary["records"][0]["key_slot"] == "fallback"


async def test_failed_request_records_requested_tokens():
    repo = Repo()
    callback = V2TokenUsageCallback(
        repo, run_id="run-1", scope="stage", task_id="task-1",
        capability_id="atomic.text.generate", attempt=2,
    )
    await callback.on_llm_error(
        RuntimeError("Rate limit: Used 1916083, Requested 110114"), run_id="call-2",
    )
    summary = summarize_usage(repo.events)
    assert summary["failed_calls"] == 1
    assert summary["requested_tokens"] == 110114
    assert summary["records"][0]["task_id"] == "task-1"


def test_summary_groups_stage_usage():
    events = [
        DomainEvent(run_id="r", type="llm.usage", payload={
            "scope": "stage", "task_id": "t", "capability_id": "scene.generate",
            "input_tokens": 9, "output_tokens": 3, "total_tokens": 12,
        }),
    ]
    summary = summarize_usage(events)
    assert summary["by_scope"]["stage"]["total_tokens"] == 12
    assert summary["by_task"][0]["capability_id"] == "scene.generate"
