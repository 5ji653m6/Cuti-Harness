import pytest

from app.chat.v2.models import ArtifactVersion
from app.video_runtime.builtin_plugins.media_inputs import resolve_media_parameters


def _artifact(artifact_id: str, artifact_type: str, uri: str) -> ArtifactVersion:
    return ArtifactVersion(
        id=artifact_id,
        artifact_id=artifact_id,
        project_id="proj",
        type=artifact_type,
        produced_by_task_id="task",
        uri=uri,
    )


def test_text_blueprint_can_describe_future_image_slots():
    parameters = {"prompt": "下一阶段提示词应声明 @图片1 控制角色身份"}

    resolve_media_parameters(parameters, [], validate_prompt_slots=False)

    assert parameters["prompt"].startswith("下一阶段")


def test_media_provider_still_rejects_a_missing_image_slot():
    parameters = {"prompt": "使用 @图片1 生成视频"}

    with pytest.raises(ValueError, match="missing images slot 1"):
        resolve_media_parameters(parameters, [], validate_prompt_slots=True)


def test_non_mv_still_appends_selected_audio_cut():
    clip = "https://cdn.example/clip.mp3"
    master = "https://cdn.example/master.mp3"
    parameters = {
        "prompt": "use @音频1",
        "audios": [clip],
        "images": ["https://cdn.example/face.webp"],
    }
    selected = [
        _artifact("img-1", "image", "https://cdn.example/face.webp"),
        _artifact("cut-1", "audio_cut", master),
    ]

    resolve_media_parameters(parameters, selected)

    assert parameters["audios"] == [clip, master]


def test_mv_keeps_explicit_urls_and_does_not_append_or_resolve_ids():
    clip = "https://cdn.example/clip.mp3"
    master = "https://cdn.example/master.mp3"
    image_uri = "https://cdn.example/face.webp"
    parameters = {
        "prompt": "use @图片1 and @音频1",
        "audios": [clip],
        "images": [image_uri],
        "workflow_mode": "mv",
        "activated_workflow": "mv",
    }
    selected = [
        _artifact("98c15dfb-f6f2-45cd-9ea6-25c12cc728b1", "image", image_uri),
        _artifact("9dbc15f2-39f4-44d3-9dd4-40d1ff76628c", "audio_cut", master),
    ]

    resolve_media_parameters(parameters, selected)

    assert parameters["audios"] == [clip]
    assert parameters["images"] == [image_uri]


def test_mv_rejects_artifact_ids_in_media_fields():
    parameters = {
        "prompt": "use @图片1",
        "images": ["98c15dfb-f6f2-45cd-9ea6-25c12cc728b1"],
        "workflow_mode": "mv",
    }
    selected = [
        _artifact("98c15dfb-f6f2-45cd-9ea6-25c12cc728b1", "image", "https://cdn.example/face.webp"),
    ]

    with pytest.raises(ValueError, match="http\\(s\\) URLs"):
        resolve_media_parameters(parameters, selected)
