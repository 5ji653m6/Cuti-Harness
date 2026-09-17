from __future__ import annotations

import pytest

from app.video_runtime.plan_utils import BuildPlanValidationError
from app.video_runtime.models import RebuildPlanItem
from app.video_runtime.video_generation_contracts import (
    contract_for_model,
    validate_video_generation_steps,
    video_generation_contracts,
)


def _video_step(duration: float, model: str = "seedance-2.0") -> RebuildPlanItem:
    return RebuildPlanItem(
        step_id="clip-1",
        action="create",
        capability="atomic.video.generate",
        output_artifact_type="video_clip",
        parameters={"model": model, "duration": duration},
    )


def test_contract_is_model_fact_not_fixed_story_segmentation() -> None:
    contract = next(
        item for item in video_generation_contracts() if item["model"] == "seedance-2.0"
    )
    assert contract["duration"] == {
        "minimum": 4, "maximum": 15, "integerSeconds": True,
    }
    assert "Do not use a fixed segment count" in contract["planningGuidance"]


def test_seedance_aliases_keep_distinct_duration_limits() -> None:
    assert contract_for_model("doubao-seedance-2-0")["duration"]["maximum"] == 15
    assert contract_for_model("bytedance/seedance-2.5/text-to-video")["duration"]["maximum"] == 30


def test_two_second_timeline_shot_cannot_become_provider_task() -> None:
    with pytest.raises(BuildPlanValidationError, match="Narrative shot timing"):
        validate_video_generation_steps([_video_step(2)])


def test_supported_generation_segment_is_accepted() -> None:
    validate_video_generation_steps([_video_step(15)])
