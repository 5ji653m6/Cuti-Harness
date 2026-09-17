from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.chat.v2.atomic_executor import execute_atomic
from app.chat.v2.models import AgentRun, ArtifactVersion, InputFile, Task


@pytest.mark.asyncio
async def test_atomic_text_receives_run_uploaded_image(monkeypatch):
    captured = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return "product facts"

    async def fake_inline(url):
        captured["source_url"] = url
        return "data:image/webp;base64,AAAA"

    monkeypatch.setattr(
        "app.llm.openai_text.generate_openai_text", fake_generate,
    )
    monkeypatch.setattr(
        "app.utils.file_utils.inline_local_image_url_for_llm", fake_inline,
    )
    run = AgentRun(
        thread_id="thread-product",
        project_id="project-product",
        user_id="user-1",
        objective="analyze product",
        idempotency_key="request-product",
        input_files=[
            InputFile(
                type="image",
                url="http://localhost:19004/files/images/product.webp",
                filename="product.jpg",
            ),
        ],
    )
    task = Task(
        run_id=run.id,
        revision=1,
        client_key="product-truth",
        capability_id="atomic.text.generate",
        objective="extract product truth",
        parameters={"prompt": "Inspect the supplied product image."},
    )

    _, artifact = await execute_atomic(
        run=run,
        task=task,
        selected=[],
        idempotency_key="attempt-product",
    )

    content = captured["content"]
    assert captured["source_url"].endswith("/files/images/product.webp")
    assert content[0] == {
        "type": "text", "text": "Inspect the supplied product image.",
    }
    assert content[1]["image_url"]["url"].startswith("data:image/webp;base64,")
    assert artifact["metadata"]["input_image_count"] == 1


@pytest.mark.asyncio
async def test_atomic_text_merges_reference_image_aliases_without_duplicates(monkeypatch):
    captured = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    async def fake_inline(url):
        return url

    monkeypatch.setattr(
        "app.llm.openai_text.generate_openai_text", fake_generate,
    )
    monkeypatch.setattr(
        "app.utils.file_utils.inline_local_image_url_for_llm", fake_inline,
    )
    image_url = "https://cdn.example/product.webp"
    run = AgentRun(
        thread_id="thread-product",
        project_id="project-product",
        user_id="user-1",
        objective="analyze product",
        idempotency_key="request-product",
        input_files=[InputFile(type="image", url=image_url)],
    )
    task = Task(
        run_id=run.id,
        revision=1,
        client_key="product-truth",
        capability_id="atomic.text.generate",
        objective="extract product truth",
        parameters={
            "prompt": "Inspect it.",
            "reference_images": [image_url],
            "input_image_urls": [image_url],
        },
    )

    _, artifact = await execute_atomic(
        run=run,
        task=task,
        selected=[],
        idempotency_key="attempt-product",
    )

    image_blocks = [
        block for block in captured["content"] if block["type"] == "image_url"
    ]
    assert len(image_blocks) == 1
    assert artifact["metadata"]["input_image_count"] == 1


@pytest.mark.asyncio
async def test_atomic_text_ignores_video_model_and_uses_configured_llm(monkeypatch):
    captured = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return "production blueprint"

    monkeypatch.setattr(
        "app.llm.openai_text.generate_openai_text", fake_generate,
    )
    monkeypatch.setattr(
        "app.chat.v2.atomic_executor.get_settings",
        lambda: SimpleNamespace(
            DEEP_AGENT_V2_MODEL="gpt-5.6-terra",
            DEEP_AGENT_V2_OPENAI_API_KEY="test-key",
            OPENAI_API_KEY_FALLBACK="",
            DEEP_AGENT_V2_OPENAI_BASE_URL="https://api.openai.com/v1",
            DEEP_AGENT_V2_TIMEOUT_SECONDS=60,
            DEEP_AGENT_V2_PROVIDER_TIMEOUT_SECONDS=900,
        ),
    )
    run = AgentRun(
        thread_id="thread-blueprint",
        project_id="project-blueprint",
        user_id="user-1",
        objective="plan a drama",
        idempotency_key="request-blueprint",
    )
    task = Task(
        run_id=run.id,
        revision=1,
        client_key="blueprint",
        capability_id="atomic.text.generate",
        objective="create blueprint",
        parameters={
            "prompt": "Create the production blueprint.",
            "model": "seedance-2.5",
        },
    )

    _, artifact = await execute_atomic(
        run=run,
        task=task,
        selected=[],
        idempotency_key="attempt-blueprint",
    )

    assert captured["model"] == "gpt-5.6-terra"
    assert captured["timeout"] == 900
    assert artifact["metadata"]["model"] == "gpt-5.6-terra"
    assert artifact["metadata"]["ignored_non_text_model"] == "seedance-2.5"


@pytest.mark.asyncio
async def test_atomic_image_routes_gpt_image_2_with_run_reference(monkeypatch):
    from app.models.image_result import ImageGenerationResult
    from app.tools.image.gpt_image_2 import edit_image_with_wavespeed_gpt_image_2

    captured = {}

    async def fake_egress(url, **_kwargs):
        return url.replace("http://localhost:19004", "https://media.example")

    async def fake_edit(*, prompt, images, runtime):
        captured.update(prompt=prompt, images=images, runtime=runtime)
        return ImageGenerationResult(
            success=True,
            image_url="https://media.example/concept.webp",
            model="gpt-image-2",
        )

    monkeypatch.setattr(
        "app.utils.media_egress.resolve_outbound_media_url", fake_egress,
    )
    monkeypatch.setattr(edit_image_with_wavespeed_gpt_image_2, "coroutine", fake_edit)
    run = AgentRun(
        thread_id="thread-product-image",
        project_id="project-product-image",
        user_id="user-1",
        objective="create concept image",
        idempotency_key="request-product-image",
        input_files=[InputFile(
            type="image",
            url="http://localhost:19004/files/images/product.webp",
        )],
    )
    task = Task(
        run_id=run.id,
        revision=1,
        client_key="concept-view",
        capability_id="atomic.image.generate",
        objective="create concept image",
        parameters={
            "prompt": "Create a front three-quarter product concept image.",
            "model": "gpt-image-2",
            "aspect_ratio": "16:9",
            "resolution": "1080p",
            "artifact_role": "product_360_reference",
        },
    )

    _, artifact = await execute_atomic(
        run=run,
        task=task,
        selected=[],
        idempotency_key="attempt-product-image",
    )

    assert captured["images"] == [
        "https://media.example/files/images/product.webp",
    ]
    assert captured["runtime"].context.model.value == "gpt-image-2"
    assert artifact["uri"] == "https://media.example/concept.webp"
    assert artifact["metadata"]["artifact_role"] == "product_360_reference"


def test_atomic_image_model_accepts_planpatch_provider_and_run_option():
    from app.chat.v2.atomic_executor import _atomic_image_model_value

    run = AgentRun(
        thread_id="thread-model",
        project_id="project-model",
        user_id="user-model",
        objective="model routing",
        idempotency_key="request-model",
        user_option={"image_generation_tool": "gpt_image_2"},
    )

    assert _atomic_image_model_value(run, {}) == "gpt-image-2"
    assert _atomic_image_model_value(run, {"provider": "gpt-image-2"}) == "gpt-image-2"
    assert _atomic_image_model_value(run, {"model": "nano_banana_2"}) == "gemini-3.1-flash-image-preview"


@pytest.mark.asyncio
async def test_atomic_video_promotes_selected_tail_frame_to_strict_i2v(monkeypatch):
    captured = {}

    async def fake_generate(profile, on_remote_submitted=None):
        captured.update(profile)
        return {
            "video_url": "https://cdn.example/continued.mp4",
            "raw_task_id": "remote-i2v",
        }

    monkeypatch.setattr(
        "app.integrations.providers.provider_bridge.generate_video", fake_generate,
    )
    run = AgentRun(
        thread_id="thread-continuity",
        project_id="project-continuity",
        user_id="user-1",
        objective="continue the scene",
        idempotency_key="request-continuity",
    )
    task = Task(
        run_id=run.id,
        revision=1,
        client_key="segment-2",
        capability_id="atomic.video.generate",
        objective="generate segment two",
        parameters={
            "prompt": "Continue the same action.",
            "provider": "wavespeed",
            "model": "seedance-2.5",
        },
    )
    selected = [
        ArtifactVersion(
            id="character-version",
            artifact_id="character",
            project_id=run.project_id,
            type="image",
            produced_by_task_id="character-task",
            uri="https://cdn.example/character.png",
            metadata={"artifact_role": "character_setting_reference"},
        ),
        ArtifactVersion(
            id="tail-version",
            artifact_id="tail",
            project_id=run.project_id,
            type="image",
            produced_by_task_id="extract-tail-task",
            uri="https://cdn.example/segment-1-tail.png",
            metadata={"position": "last", "source_video_url": "https://cdn.example/segment-1.mp4"},
        ),
    ]

    _, artifact = await execute_atomic(
        run=run,
        task=task,
        selected=selected,
        idempotency_key="attempt-continuity",
    )

    assert captured["generation_mode"] == "i2v"
    assert captured["start_image_url"] == "https://cdn.example/segment-1-tail.png"
    assert captured["images"] == ["https://cdn.example/character.png"]
    assert artifact["uri"] == "https://cdn.example/continued.mp4"


@pytest.mark.asyncio
async def test_atomic_video_resolves_artifact_ids_to_urls_without_duplicates(monkeypatch):
    captured = {}

    async def fake_generate(profile, on_remote_submitted=None):
        captured.update(profile)
        return {
            "video_url": "https://cdn.example/segment.mp4",
            "raw_task_id": "remote-t2v",
        }

    monkeypatch.setattr(
        "app.integrations.providers.provider_bridge.generate_video", fake_generate,
    )
    run = AgentRun(
        thread_id="thread-multiref",
        project_id="project-multiref",
        user_id="user-1",
        objective="generate a multi-reference segment",
        idempotency_key="request-multiref",
    )
    selected = [
        ArtifactVersion(
            id="maya-version",
            artifact_id="maya-artifact",
            project_id=run.project_id,
            type="image",
            produced_by_task_id="maya-task",
            uri="https://cdn.example/maya.webp",
        ),
        ArtifactVersion(
            id="apartment-version",
            artifact_id="apartment-artifact",
            project_id=run.project_id,
            type="image",
            produced_by_task_id="apartment-task",
            uri="https://cdn.example/apartment.webp",
        ),
    ]
    task = Task(
        run_id=run.id,
        revision=1,
        client_key="segment-1",
        capability_id="atomic.video.generate",
        objective="generate segment one",
        input_artifact_version_ids=[item.id for item in selected],
        parameters={
            "prompt": "Generate the first segment.",
            "provider": "wavespeed",
            "model": "seedance-2.5",
            "generation_mode": "t2v",
            # The plan normalizer may mirror selected version IDs here.
            "images": ["maya-version", "apartment-version"],
        },
    )

    _, artifact = await execute_atomic(
        run=run,
        task=task,
        selected=selected,
        idempotency_key="attempt-multiref",
    )

    assert captured["generation_mode"] == "t2v"
    assert captured["images"] == [
        "https://cdn.example/maya.webp",
        "https://cdn.example/apartment.webp",
    ]
    assert artifact["uri"] == "https://cdn.example/segment.mp4"


@pytest.mark.asyncio
async def test_atomic_video_forwards_runtime_source_and_audio_artifact_types(monkeypatch):
    captured = {}

    async def fake_generate(profile, on_remote_submitted=None):
        captured.update(profile)
        return {
            "video_url": "https://cdn.example/product-mv.mp4",
            "raw_task_id": "remote-product-mv",
        }

    monkeypatch.setattr(
        "app.integrations.providers.provider_bridge.generate_video", fake_generate,
    )
    run = AgentRun(
        thread_id="thread-runtime-sources",
        project_id="project-runtime-sources",
        user_id="user-1",
        objective="generate from project sources",
        idempotency_key="request-runtime-sources",
    )
    selected = [
        ArtifactVersion(
            id="product-version",
            artifact_id="source:product",
            project_id=run.project_id,
            type="source_image",
            produced_by_task_id="upload-product",
            uri="https://cdn.example/product.webp",
        ),
        ArtifactVersion(
            id="music-window-version",
            artifact_id="audio:window",
            project_id=run.project_id,
            type="audio_segment",
            produced_by_task_id="trim-music",
            uri="https://cdn.example/music-window.mp3",
        ),
    ]
    task = Task(
        run_id=run.id,
        revision=1,
        client_key="product-mv-shot",
        capability_id="atomic.video.generate",
        objective="generate product MV shot",
        parameters={
            "prompt": "Keep the exact product identity and follow the beat.",
            "provider": "wavespeed",
            "model": "doubao-seedance-2-0",
            "generation_mode": "t2v",
            "reference_urls": ["source:product"],
            "audio_urls": ["audio:window"],
        },
    )

    await execute_atomic(
        run=run,
        task=task,
        selected=selected,
        idempotency_key="attempt-runtime-sources",
    )

    assert captured["images"] == ["https://cdn.example/product.webp"]
    assert captured["audios"] == ["https://cdn.example/music-window.mp3"]
