import pytest

from app.chat.v2.atomic_executor import _final_prompt
from app.chat.v2.models import Task


def _task(parameters):
    return Task(
        run_id="run-1",
        revision=1,
        client_key="atomic-1",
        capability_id="atomic.text.generate",
        objective="business objective that must not become the model prompt",
        parameters=parameters,
    )


def test_atomic_requires_an_explicit_final_prompt():
    with pytest.raises(ValueError, match="requires parameters.prompt"):
        _final_prompt(_task({}))


def test_atomic_uses_prompt_verbatim_without_objective_or_style_injection():
    prompt = "Return exactly the requested product specification."
    assert _final_prompt(_task({"prompt": prompt})) == prompt
