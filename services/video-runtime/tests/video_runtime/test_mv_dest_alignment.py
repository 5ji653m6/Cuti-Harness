"""MV compiler alignment: helper Skills plus DeepSeek-named tools."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.video_runtime.models import MediaArtifactVersion, VideoSpec
from app.video_runtime.plugins import PluginContext, VideoPluginRegistry
from app.video_runtime.skill_workflows import load_workflow_skills
from app.video_runtime.skills import VideoSkillRuntime
from app.video_runtime.workflow_plans import SUPPORTED_WORKFLOW_MODES


class TestDestMvCompileGraph(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.skills = VideoSkillRuntime()
        plugins = VideoPluginRegistry()
        await load_workflow_skills(plugins, self.skills)
        self.plugin = plugins.get("cuti.skill-workflows").implementation

    async def _compile(self, **audio) -> object:
        spec = VideoSpec.model_validate({
            "title": "dest mv alignment",
            "target_duration_seconds": 10,
            "workflow_id": "mv",
            "providers": {"video": "minimax-h3"},
            "characters": [{
                "id": "hero", "name": "Hero", "appearance": "black hair",
            }],
            "shots": [{
                "id": str(index), "order": index,
                "duration_seconds": 5,
                "beat": f"beat {index}", "visual_prompt": f"shot {index}",
                "character_ids": ["hero"],
            } for index in (1, 2)],
            "audio": {"bgm_prompt": "sung pop chorus", **audio},
        })
        return await self.plugin.compile_build_plan(
            PluginContext(project_id="project-1", values={
                "base_project_version_id": "version-1",
            }),
            spec,
        )

    async def test_mode_mv_is_installed_and_compiled(self) -> None:
        self.assertIn("mv", SUPPORTED_WORKFLOW_MODES)
        views = {item["id"]: item for item in self.plugin.describe_workflows()}
        self.assertEqual(views["mv"]["mode"], "mv")
        self.assertTrue(views["mv"]["available"])
        self.assertEqual(
            list(views["mv"]["pipeline"]),
            [
                "suno.generate",
                "media.audio_analyze",
                "media.audio_cut",
                "atomic.image.generate",
                "api.provider.generate",
                "media.concat",
                "media.mix_audio",
                "media.transcribe",
                "media.hyperframes_caption",
            ],
        )

    async def test_compile_graph_follows_dest_pipeline(self) -> None:
        plan = await self._compile(subtitles=True)
        by_id = {item.step_id: item for item in plan.items}
        self.assertNotIn("research", by_id)
        self.assertNotIn("script", by_id)
        self.assertNotIn("storyboard", by_id)
        self.assertEqual(by_id["music"].capability, "suno.generate")
        self.assertEqual(by_id["music"].parameters["prompt"], "sung pop chorus")
        self.assertNotIn("duration", by_id["music"].parameters)
        self.assertEqual(by_id["music"].parameters["title"], "dest mv alignment")
        self.assertNotIn("auto_lyrics", by_id["music"].parameters)
        self.assertNotIn("mv", by_id["music"].parameters)
        self.assertNotIn("look", by_id)
        self.assertEqual(by_id["character-hero-reference"].capability, "atomic.image.generate")
        self.assertFalse(by_id["character-hero-reference"].skill_ids)
        self.assertEqual(by_id["characters"].capability, "runtime.artifact.persist")
        self.assertEqual(by_id["mv-shot-plan"].capability, "runtime.artifact.persist")
        self.assertEqual(by_id["music-analysis"].capability, "media.audio_analyze")
        self.assertEqual(by_id["music-cut"].capability, "media.audio_cut")
        self.assertNotIn("music-window", by_id)
        self.assertFalse(
            any(item.step_id.endswith("-audio") and item.capability == "media.audio.trim"
                for item in plan.items)
        )
        clips = [
            item for item in plan.items if item.capability == "api.provider.generate"
        ]
        self.assertEqual(len(clips), 2)
        for clip in clips:
            self.assertEqual(clip.parameters["model"], "minimax-h3")
            self.assertEqual(clip.parameters["prompt"], f"shot {clip.step_id.split('-')[1]}")
            self.assertNotIn("@音频1", clip.parameters["prompt"])
            self.assertNotIn("start_image_from_step", clip.parameters)
            self.assertEqual(clip.parameters["audio_reference_from_step"], "music-cut")
            self.assertEqual(clip.parameters["reference_from_steps"], ["character-hero-reference"])
            self.assertEqual(
                clip.parameters["audio_segment_index"],
                int(clip.step_id.split("-")[1]) - 1,
            )
            self.assertFalse(clip.skill_ids)
        self.assertNotIn("shot-1-tail", by_id)
        self.assertEqual(by_id["assembled-video"].capability, "media.concat")
        self.assertEqual(by_id["mixed-video"].capability, "media.mix_audio")
        self.assertEqual(by_id["mixed-video"].parameters["audio_step"], "music-cut")
        self.assertEqual(by_id["mixed-video"].parameters["mode"], "replace")
        self.assertEqual(by_id["transcription"].capability, "media.transcribe")
        self.assertEqual(by_id["final-video"].capability, "media.hyperframes_caption")
        self.assertNotIn("style", by_id["final-video"].parameters)

    async def test_look_generate_uses_uploaded_identity(self) -> None:
        identity = MediaArtifactVersion(
            id="identity-v1", artifact_id="identity",
            project_id="project-1", type="source_image",
            uri="https://example.test/identity.png",
            title="identity",
        )
        spec = VideoSpec.model_validate({
            "title": "dest mv look",
            "target_duration_seconds": 5,
            "workflow_id": "mv",
            "providers": {"video": "minimax-h3"},
            "source_asset_ids": ["identity"],
            "characters": [{
                "id": "hero", "name": "Hero", "appearance": "black hair",
            }],
            "shots": [{
                "id": "1", "order": 1, "duration_seconds": 5,
                "beat": "chorus", "visual_prompt": "shot",
                "character_ids": ["hero"],
                "reference_asset_ids": ["identity"],
            }],
            "audio": {"bgm_prompt": "song", "subtitles": False},
        })
        plan = await self.plugin.compile_build_plan(
            PluginContext(project_id="project-1", values={
                "base_project_version_id": "version-1",
                "source_artifacts": {"identity": identity},
            }),
            spec,
        )
        look = next(
            item for item in plan.items if item.step_id == "character-hero-reference"
        )
        self.assertEqual(look.capability, "atomic.image.generate")
        self.assertFalse(look.skill_ids)
        self.assertIn("black hair", look.parameters["prompt"])
        self.assertEqual(look.parameters["reference_from_steps"], ["source-1"])
        clip = next(
            item for item in plan.items if item.capability == "api.provider.generate"
        )
        self.assertEqual(
            clip.parameters["reference_from_steps"],
            ["character-hero-reference", "source-1"],
        )

    async def test_captions_pass_through_caption_html(self) -> None:
        spec = VideoSpec.model_validate({
            "title": "dest mv captions",
            "target_duration_seconds": 5,
            "workflow_id": "mv",
            "providers": {"video": "minimax-h3"},
            "workflow_parameters": {
                "caption_html": "<!doctype html><html></html>",
            },
            "characters": [{
                "id": "hero", "name": "Hero", "appearance": "black hair",
            }],
            "shots": [{
                "id": "1", "order": 1, "duration_seconds": 5,
                "beat": "beat", "visual_prompt": "shot",
                "character_ids": ["hero"],
            }],
            "audio": {"bgm_prompt": "song", "subtitles": True},
        })
        plan = await self.plugin.compile_build_plan(
            PluginContext(project_id="project-1", values={
                "base_project_version_id": "version-1",
            }),
            spec,
        )
        by_id = {item.step_id: item for item in plan.items}
        self.assertEqual(by_id["transcription"].capability, "media.transcribe")
        self.assertEqual(by_id["final-video"].capability, "media.hyperframes_caption")
        self.assertEqual(
            by_id["final-video"].parameters["caption_html"],
            "<!doctype html><html></html>",
        )
        self.assertNotIn("style", by_id["final-video"].parameters)

    async def test_compiler_caption_step_does_not_invent_style(self) -> None:
        spec = VideoSpec.model_validate({
            "title": "dest mv original captions",
            "target_duration_seconds": 5,
            "workflow_id": "mv",
            "providers": {"video": "minimax-h3"},
            "characters": [{
                "id": "hero", "name": "Hero", "appearance": "black hair",
            }],
            "shots": [{
                "id": "1", "order": 1, "duration_seconds": 5,
                "beat": "beat", "visual_prompt": "shot",
                "character_ids": ["hero"],
            }],
            "audio": {"bgm_prompt": "song", "subtitles": True},
        })
        plan = await self.plugin.compile_build_plan(
            PluginContext(project_id="project-1", values={
                "base_project_version_id": "version-1",
            }),
            spec,
        )
        by_id = {item.step_id: item for item in plan.items}
        self.assertEqual(by_id["transcription"].capability, "media.transcribe")
        self.assertEqual(by_id["final-video"].capability, "media.hyperframes_caption")
        self.assertNotIn("style", by_id["final-video"].parameters)
        self.assertNotIn("caption_html", by_id["final-video"].parameters)

    async def test_dest_tool_fields_land_on_the_matching_step(self) -> None:
        spec = VideoSpec.model_validate({
            "title": "dest mv bag",
            "target_duration_seconds": 10,
            "workflow_id": "mv",
            "providers": {"video": "minimax-h3"},
            "workflow_parameters": {
                "auto_lyrics": True,
                "tags": "pop, female vocal",
                "duration": 120,
                "segments": [{"start_sec": 0, "duration": 5}, {"start_sec": 5, "duration": 5}],
                "caption_html": "<!doctype html><html></html>",
            },
            "characters": [{
                "id": "hero", "name": "Hero", "appearance": "black hair",
            }],
            "shots": [{
                "id": str(index), "order": index, "duration_seconds": 5,
                "beat": "beat", "visual_prompt": "shot",
                "character_ids": ["hero"],
            } for index in (1, 2)],
            "audio": {"bgm_prompt": "song", "subtitles": False},
        })
        plan = await self.plugin.compile_build_plan(
            PluginContext(project_id="project-1", values={
                "base_project_version_id": "version-1",
            }),
            spec,
        )
        by_id = {item.step_id: item for item in plan.items}
        music = by_id["music"].parameters
        cut = by_id["music-cut"].parameters
        clips = [
            item.parameters for item in plan.items
            if item.capability == "api.provider.generate"
        ]
        self.assertEqual(music["prompt"], "song")
        self.assertEqual(music["tags"], "pop, female vocal")
        self.assertEqual(music["duration"], 120)
        self.assertNotIn("auto_lyrics", music)
        self.assertEqual(len(cut["segments"]), 2)
        self.assertEqual(cut["duration"], 10)
        self.assertEqual(clips[0]["audio_segment_index"], 0)
        self.assertEqual(clips[1]["audio_segment_index"], 1)
        self.assertNotIn("caption_html", clips[0])
        self.assertNotIn("auto_lyrics", clips[0])

    async def test_no_subtitles_stops_at_replace_mix(self) -> None:
        plan = await self._compile(subtitles=False)
        by_id = {item.step_id: item for item in plan.items}
        self.assertNotIn("transcription", by_id)
        self.assertEqual(by_id["final-video"].capability, "media.mix_audio")

    async def test_seedance_uses_the_same_graph(self) -> None:
        spec = VideoSpec.model_validate({
            "title": "seedance mv optional path",
            "target_duration_seconds": 10,
            "workflow_id": "mv",
            "providers": {"video": "doubao-seedance-2-0"},
            "characters": [{
                "id": "hero", "name": "Hero", "appearance": "black hair",
            }],
            "shots": [{
                "id": str(index), "order": index,
                "duration_seconds": 5,
                "beat": "beat", "visual_prompt": "shot",
                "character_ids": ["hero"],
            } for index in (1, 2)],
            "audio": {"bgm_prompt": "song", "subtitles": False},
        })
        plan = await self.plugin.compile_build_plan(
            PluginContext(project_id="project-1", values={
                "base_project_version_id": "version-1",
            }),
            spec,
        )
        clip = next(
            item for item in plan.items if item.capability == "api.provider.generate"
        )
        self.assertEqual(clip.parameters["model"], "doubao-seedance-2-0")
        self.assertNotIn("audio_reference_from_step", clip.parameters)
        self.assertNotIn("audio_segment_index", clip.parameters)
        self.assertFalse(clip.skill_ids)
        self.assertNotIn("shot-1-tail", {item.step_id for item in plan.items})

    async def test_h3_without_an_image_fails_before_provider_submission(self) -> None:
        spec = VideoSpec.model_validate({
            "title": "invalid image-free H3 MV",
            "target_duration_seconds": 5,
            "workflow_id": "mv",
            "providers": {"video": "minimax-h3"},
            "shots": [{
                "id": "1", "order": 1, "duration_seconds": 5,
                "beat": "chorus", "visual_prompt": "an abstract pulse",
            }],
            "audio": {"bgm_prompt": "song", "subtitles": False},
        })
        with self.assertRaisesRegex(
            ValueError,
            "MiniMax H3 shots require at least one image reference",
        ):
            await self.plugin.compile_build_plan(
                PluginContext(project_id="project-1", values={
                    "base_project_version_id": "version-1",
                }),
                spec,
            )


class TestDestMvCompileWithInstalledPlugins(unittest.IsolatedAsyncioTestCase):
    async def test_full_plugin_load_keeps_dest_capability_ids(self) -> None:
        from app.video_runtime.runtime import VideoBuildRuntime
        from app.video_runtime.skill_workflows import load_workflow_skills

        runtime = VideoBuildRuntime()
        await runtime.plugins.load_directories([
            Path(__file__).resolve().parents[2] / "plugins",
        ])
        await load_workflow_skills(runtime.plugins, runtime.skills)
        project, version = await runtime.create_project(user_id="user", title="mv")
        identity = await runtime.add_artifact(MediaArtifactVersion(
            artifact_id="identity",
            project_id=project.id,
            type="source_image",
            uri="https://example.test/identity.png",
            title="identity",
        ))
        project = await runtime.repo.get_project(project.id)
        spec = VideoSpec.model_validate({
            "title": "五秒MV探针",
            "target_duration_seconds": 5,
            "aspect_ratio": "9:16",
            "resolution": "768p",
            "workflow_id": "mv",
            "providers": {"video": "minimax-h3"},
            "source_asset_ids": [identity.artifact_id],
            "shots": [{
                "id": "1", "order": 1, "duration_seconds": 5,
                "beat": "chorus",
                "visual_prompt": "a singer on a dusk street",
                "reference_asset_ids": [identity.artifact_id],
            }],
            "audio": {"bgm_prompt": "short sung pop chorus"},
        })
        plan = await runtime.plan_project(
            project_id=project.id,
            base_project_version_id=project.current_version_id,
            video_spec=spec,
            idempotency_key="mv-5s-path",
        )
        create = [
            (item.step_id, item.capability)
            for item in plan.items if item.action == "create"
        ]
        self.assertEqual(
            [capability for _step, capability in create if capability != "runtime.artifact.persist"],
            [
                "suno.generate",
                "media.audio_analyze",
                "media.audio_cut",
                "api.provider.generate",
                "media.timeline.compose",
                "media.concat",
                "media.mix_audio",
                "media.transcribe",
                "media.hyperframes_caption",
            ],
        )
        self.assertNotIn("character-hero-reference", {item.step_id for item in plan.items})
        self.assertNotIn("atomic.music.generate", {item.capability for item in plan.items})
        self.assertNotIn("atomic.image.generate", {item.capability for item in plan.items})
        self.assertNotIn("atomic.video.generate", {item.capability for item in plan.items})
        clip = next(item for item in plan.items if item.capability == "api.provider.generate")
        self.assertEqual(clip.parameters["model"], "minimax-h3")
        self.assertEqual(clip.parameters["audio_reference_from_step"], "music-cut")
        self.assertEqual(clip.parameters["reference_from_steps"], ["source-1"])


class TestDestMvCapabilityIds(unittest.TestCase):
    def test_dest_pipeline_ids_are_real_capabilities(self) -> None:
        from app.capabilities.models import CapabilityRegistry

        registry = CapabilityRegistry()
        for capability_id in (
            "suno.generate",
            "media.audio_analyze",
            "media.audio_cut",
            "atomic.image.generate",
            "api.provider.generate",
            "media.concat",
            "media.mix_audio",
            "media.transcribe",
            "media.hyperframes_caption",
        ):
            item = registry.get(capability_id)
            self.assertEqual(item.id, capability_id)
        self.assertEqual(
            registry.get("suno.generate").parameters_schema["properties"]["mv"]["default"],
            "chirp-v5-5",
        )
        self.assertEqual(registry.get("media.audio_cut").service_target, "media_audio_cut")
        self.assertNotEqual(registry.canonical_id("media.audio.trim"), "media.audio_cut")
        self.assertNotIn(
            "media.audio_trim",
            {item["id"] for item in registry.prompt_view()},
        )

    def test_media_core_plugin_lists_each_capability_once(self) -> None:
        import yaml

        manifest = yaml.safe_load(
            (Path(__file__).resolve().parents[2] / "plugins" / "cuti-media-core" / "video-plugin.yaml")
            .read_text(encoding="utf-8")
        )
        capabilities = manifest["contributions"]["capabilities"]
        plan_patch = manifest["contributions"]["plan_patch_capabilities"]
        self.assertEqual(capabilities, list(dict.fromkeys(capabilities)))
        self.assertEqual(plan_patch, list(dict.fromkeys(plan_patch)))
        self.assertNotIn("media.audio.analyze", capabilities)
        self.assertNotIn("media.audio.cut", capabilities)
        self.assertNotIn("media.subtitle.compose", capabilities)
        self.assertNotIn("media.subtitle.burn", capabilities)
        self.assertTrue(set(plan_patch) <= set(capabilities))


DEST_SUNO_READS = (
    "references/bitwize/skills/lyric-writer/UPSTREAM.md",
    "references/bitwize/skills/pronunciation-specialist/UPSTREAM.md",
    "references/bitwize/skills/lyric-refiner/UPSTREAM.md",
    "references/bitwize/skills/lyric-reviewer/UPSTREAM.md",
    "references/bitwize/skills/suno-engineer/UPSTREAM.md",
    "references/bitwize/skills/pre-generation-check/UPSTREAM.md",
)


class TestDestMvLiveSkillPath(unittest.TestCase):
    """Hit the same HTTP load path DeepSeek uses, against dest's real tool list."""

    def setUp(self) -> None:
        import asyncio
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.video_runtime.api import get_runtime, router, set_runtime
        from app.video_runtime.runtime import VideoBuildRuntime
        from app.video_runtime.skill_workflows import load_workflow_skills

        self._previous_runtime = get_runtime()
        self._set_runtime = set_runtime
        self.skills = VideoSkillRuntime()
        plugins = VideoPluginRegistry()
        asyncio.run(load_workflow_skills(plugins, self.skills))
        self.runtime = VideoBuildRuntime(plugins=plugins, skill_runtime=self.skills)
        set_runtime(self.runtime)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.headers = {"X-Video-User-Id": "user-1"}

    def tearDown(self) -> None:
        self.client.close()
        self._set_runtime(self._previous_runtime)

    def test_mv_workflow_load_returns_skill_and_reference(self) -> None:
        response = self.client.get("/api/video/workflows/mv", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["id"], "mv")
        self.assertIn('video_skill_load("suno-song")', data["instructions"])
        self.assertIn('video_skill_load("h3")', data["instructions"])
        self.assertIn("reference.md", data["resources"])
        contents = {item["path"]: item["content"] for item in data["resourceContents"]}
        self.assertIn("reference.md", contents)
        self.assertGreater(len(contents["reference.md"]), 100)

    def test_dest_suno_checklist_files_are_readable(self) -> None:
        skill = self.client.get("/api/video/skills/suno-song", headers=self.headers)
        self.assertEqual(skill.status_code, 200, skill.text)
        body = skill.json()["data"]
        self.assertIn("13 点自检", body["instructions"])
        self.assertIn("pre-generation-check", body["instructions"])
        for path in DEST_SUNO_READS:
            self.assertIn(path, body["resources"], path)
            resource = self.client.get(
                "/api/video/skills/suno-song/resources",
                headers=self.headers,
                params={"path": path},
            )
            self.assertEqual(resource.status_code, 200, resource.text)
            content = resource.json()["data"]["content"]
            self.assertGreater(len(content), 100, path)

    def test_h3_and_caption_helpers_load(self) -> None:
        for skill_id in ("video-research", "h3", "hyperframes-captions"):
            response = self.client.get(f"/api/video/skills/{skill_id}", headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["data"]["instructions"].strip())


class TestDestMvDoesNotPreactivateHelpers(unittest.IsolatedAsyncioTestCase):
    async def test_mv_does_not_inject_helper_skill_ids(self) -> None:
        from app.video_runtime.deepseek_bff import _effective_skill_selection
        from app.video_runtime.runtime import VideoBuildRuntime

        runtime = VideoBuildRuntime()
        project, _version = await runtime.create_project(user_id="user", title="mv")
        workflow, activated = await _effective_skill_selection(
            runtime, project.id, "mv", [],
        )
        self.assertEqual(workflow, "mv")
        self.assertEqual(activated, [])

    async def test_user_dollar_helper_still_activates(self) -> None:
        from app.video_runtime.deepseek_bff import (
            _effective_skill_selection,
            _requested_skill_selection,
        )
        from app.video_runtime.runtime import VideoBuildRuntime

        runtime = VideoBuildRuntime()
        if not runtime.skills.catalog.has("suno-song"):
            self.skipTest("suno-song is not installed")
        project, _version = await runtime.create_project(user_id="user", title="mv")
        requested_workflow, requested_activated = _requested_skill_selection(
            runtime, "mv", [], "$suno-song make a song",
        )
        workflow, activated = await _effective_skill_selection(
            runtime, project.id, requested_workflow, requested_activated,
        )
        self.assertEqual(workflow, "mv")
        self.assertEqual(activated, ["suno-song"])
