from app.video_runtime.models import RebuildPlanItem
from app.video_runtime.runtime import uploaded_source_must_be_declared


def _image_step(**parameters) -> RebuildPlanItem:
    return RebuildPlanItem(
        step_id="identity-sheet",
        action="create",
        capability="atomic.image.generate",
        output_artifact_type="image",
        depends_on=["source-1"],
        parameters=parameters,
    )


def test_image_task_depending_on_source_must_declare_media() -> None:
    uploaded_source_must_be_declared(_image_step(
        prompt="lock identity",
        reference_from_steps=["source-1"],
    ))
    uploaded_source_must_be_declared(_image_step(
        prompt="lock identity",
        images=["93571c6f-5bd8-4d67-be99-e7fff48dc41b"],
    ))


def test_image_task_depending_on_source_without_media_is_rejected() -> None:
    try:
        uploaded_source_must_be_declared(_image_step(prompt="keep the subject"))
    except ValueError as exc:
        assert "depends_on only schedules" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_non_image_or_no_source_dep_is_unchanged() -> None:
    uploaded_source_must_be_declared(RebuildPlanItem(
        step_id="clip",
        action="create",
        capability="api.provider.generate",
        output_artifact_type="video",
        depends_on=["source-1"],
        parameters={"prompt": "clip", "model": "minimax-h3"},
    ))
    uploaded_source_must_be_declared(RebuildPlanItem(
        step_id="invented-scene",
        action="create",
        capability="atomic.image.generate",
        output_artifact_type="image",
        depends_on=["script"],
        parameters={"prompt": "empty room"},
    ))
