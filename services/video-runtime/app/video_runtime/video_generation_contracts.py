"""Provider facts shared by Agent planning and deterministic plan validation."""

from __future__ import annotations

from typing import Any, Iterable

from .plan_utils import BuildPlanValidationError
from .models import RebuildPlanItem


_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "model": "seedance-2.5",
        "aliases": ["seedance2.5", "seedance-2-5", "seedance_2_5"],
        "duration": {"minimum": 4, "maximum": 30, "integerSeconds": True},
        "supports": {
            "nativeAudio": True, "startFrame": True, "endFrame": True,
            "multipleReferences": True,
        },
    },
    {
        "model": "seedance-2.0",
        "aliases": [
            "seedance2", "seedance-2", "seedance_2", "doubao-seedance-2-0",
            "wavespeed-seedance-2", "wavespeed", "ark", "auto",
        ],
        "duration": {"minimum": 4, "maximum": 15, "integerSeconds": True},
        "supports": {
            "nativeAudio": True, "startFrame": True, "endFrame": True,
            "multipleReferences": True,
        },
    },
)


def video_generation_contracts() -> list[dict[str, Any]]:
    """Return JSON-safe execution facts for the model-facing Workflow contract."""
    return [
        {
            **contract,
            "planningGuidance": (
                "Narrative shot duration is an editing/timeline decision, not automatically "
                "a valid provider generation duration. Choose generation segments from the "
                "story structure and this model's limits; one generation segment may contain "
                "multiple narrative shots. Add deterministic trim/concat steps when the edit "
                "timing differs from generated media. Do not use a fixed segment count."
            ),
        }
        for contract in _CONTRACTS
    ]


def _normalized(value: str) -> str:
    return value.strip().casefold().replace("_", "-")


def contract_for_model(model: str | None) -> dict[str, Any] | None:
    raw = _normalized(model or "seedance-2.0")
    for contract in _CONTRACTS:
        candidates = [contract["model"], *contract["aliases"]]
        if any(_normalized(str(candidate)) in raw for candidate in candidates):
            return contract
    return None


def validate_video_generation_steps(items: Iterable[RebuildPlanItem]) -> None:
    """Reject impossible provider tasks while leaving segmentation to the Agent."""
    for item in items:
        if item.action != "create" or item.capability not in {
            "atomic.video.generate", "api.provider.generate", "api.ark_protocol.generate",
        }:
            continue
        contract = contract_for_model(str(
            item.parameters.get("model") or item.parameters.get("provider") or "seedance-2.0"
        ))
        if contract is None:
            continue
        raw_duration = item.parameters.get("duration", item.parameters.get("duration_seconds"))
        if raw_duration is None:
            continue
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError) as exc:
            raise BuildPlanValidationError(
                f"video task {item.step_id} has invalid duration {raw_duration!r}"
            ) from exc
        limits = contract["duration"]
        valid = limits["minimum"] <= duration <= limits["maximum"]
        if limits["integerSeconds"]:
            valid = valid and duration.is_integer()
        if not valid:
            raise BuildPlanValidationError(
                f"video task {item.step_id} requests {duration:g}s, but "
                f"{contract['model']} accepts whole-second generation segments from "
                f"{limits['minimum']}s to {limits['maximum']}s. Narrative shot timing is "
                "not a provider duration: re-plan generation segments from story boundaries "
                "and add deterministic trim/concat steps when needed; do not assume a fixed "
                "number of segments."
            )
