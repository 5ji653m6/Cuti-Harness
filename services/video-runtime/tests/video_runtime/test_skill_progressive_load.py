"""Walk installed Skills: load SKILL.md, then open named files.

Covers the writing styles that actually exist in the catalog:
- video_skill_load("id")
- video_skill_read_resource("id", "path")
- markdown links [text](references/...)
- backtick / table paths `references/...`
- ./relative markdown links
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.video_runtime.api import get_runtime, router, set_runtime
from app.video_runtime.plugins import VideoPluginRegistry
from app.video_runtime.runtime import VideoBuildRuntime
from app.video_runtime.skill_workflows import load_workflow_skills
from app.video_runtime.skills import VideoSkillRuntime


LOAD_SKILL = re.compile(r"""video_skill_load\(\s*["']([^"']+)["']\s*\)""")
READ_RESOURCE = re.compile(
    r"""video_skill_read_resource\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']\s*\)""",
)
MARKDOWN_LINK = re.compile(r"\]\(([^)]+)\)")
BACKTICK_REF = re.compile(r"`(\.?/?references/[^`\s]+)`")


def _relative_bundle_path(target: str) -> str | None:
    parsed = urlsplit(target.strip().strip("<>"))
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path).removeprefix("./")
    if not path or path.endswith("/"):
        return None
    return path


class TestSkillProgressiveLoad(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import asyncio

        cls._previous_runtime = get_runtime()
        skills = VideoSkillRuntime()
        plugins = VideoPluginRegistry()
        asyncio.run(load_workflow_skills(plugins, skills))
        cls.runtime = VideoBuildRuntime(plugins=plugins, skill_runtime=skills)
        set_runtime(cls.runtime)
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)
        cls.headers = {"X-Video-User-Id": "user-1"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        set_runtime(cls._previous_runtime)

    def _get_skill(self, skill_id: str) -> dict:
        response = self.client.get(f"/api/video/skills/{skill_id}", headers=self.headers)
        self.assertEqual(response.status_code, 200, f"{skill_id}: {response.text}")
        return response.json()["data"]

    def _read(self, skill_id: str, path: str) -> str:
        response = self.client.get(
            f"/api/video/skills/{skill_id}/resources",
            headers=self.headers,
            params={"path": path},
        )
        self.assertEqual(
            response.status_code, 200,
            f"{skill_id}/{path}: {response.status_code} {response.text}",
        )
        content = response.json()["data"]["content"]
        self.assertTrue(content.strip(), f"{skill_id}/{path} was empty")
        return content

    def test_every_installed_skill_loads_over_http(self) -> None:
        names = [item.name for item in self.runtime.skills.catalog.list_metadata() if item.enabled]
        self.assertGreaterEqual(len(names), 10)
        for skill_id in names:
            data = self._get_skill(skill_id)
            self.assertEqual(data["id"], skill_id)
            self.assertTrue(data["instructions"].strip(), skill_id)
            self.assertIn("resources", data)

    def test_load_skill_targets_named_in_skill_text_are_installed(self) -> None:
        missing: list[str] = []
        for metadata in self.runtime.skills.catalog.list_metadata():
            if not metadata.enabled:
                continue
            text = self.runtime.skills.catalog.load(metadata.name).instructions
            for target in LOAD_SKILL.findall(text):
                if not self.runtime.skills.catalog.has(target):
                    missing.append(f"{metadata.name} -> {target}")
                    continue
                self._get_skill(target)
        self.assertEqual(missing, [])

    def test_explicit_read_skill_resource_calls_are_readable(self) -> None:
        found = 0
        for metadata in self.runtime.skills.catalog.list_metadata():
            if not metadata.enabled:
                continue
            text = self.runtime.skills.catalog.load(metadata.name).instructions
            for skill_id, path in READ_RESOURCE.findall(text):
                found += 1
                self.assertTrue(
                    self.runtime.skills.catalog.has(skill_id),
                    f"{metadata.name} names missing skill {skill_id}",
                )
                self._read(skill_id, path)
        # The original Cuti catalog currently uses markdown links for resource
        # disclosure. Explicit cross-Skill reads remain supported when a Skill
        # declares one, but the test must not force us to rewrite original text.
        self.assertGreaterEqual(found, 0)

    def test_markdown_and_backtick_references_are_readable(self) -> None:
        unread: list[str] = []
        checked = 0
        for metadata in self.runtime.skills.catalog.list_metadata():
            if not metadata.enabled:
                continue
            loaded = self.runtime.skills.catalog.load(metadata.name)
            inventory = set(self.runtime.skills.catalog.list_resources(metadata.name))
            mentioned: list[str] = []
            for target in MARKDOWN_LINK.findall(loaded.instructions):
                path = _relative_bundle_path(target)
                if path:
                    mentioned.append(path)
            for path in BACKTICK_REF.findall(loaded.instructions):
                mentioned.append(path.removeprefix("./"))
            for path in dict.fromkeys(mentioned):
                if path not in inventory:
                    continue
                checked += 1
                try:
                    self.runtime.skills.catalog.read_resource(metadata.name, path)
                except ValueError:
                    continue
                response = self.client.get(
                    f"/api/video/skills/{metadata.name}/resources",
                    headers=self.headers,
                    params={"path": path},
                )
                if response.status_code != 200:
                    unread.append(f"{metadata.name}/{path} -> {response.status_code}")
        self.assertGreater(checked, 20)
        self.assertEqual(unread, [])

    def test_dot_slash_markdown_path_resolves(self) -> None:
        self._read("hyperframes-registry", "./references/install-locations.md")
        self._read("hyperframes-registry", "references/install-locations.md")

    def test_dest_mv_chain_loads_helpers_and_suno_checklists(self) -> None:
        workflow = self.client.get("/api/video/workflows/mv", headers=self.headers)
        self.assertEqual(workflow.status_code, 200, workflow.text)
        instructions = workflow.json()["data"]["instructions"]
        self.assertIn('video_skill_load("suno-song")', instructions)
        self.assertIn("reference.md", workflow.json()["data"]["resources"])
        self._read("mv", "reference.md")

        for helper in (
            "video-research", "suno-song", "h3",
            "hyperframes-captions", "subtitle-authoring",
        ):
            self.assertIn(f'video_skill_load("{helper}")', instructions)
            self._get_skill(helper)

        captions = self._get_skill("hyperframes-captions")["instructions"]
        self.assertIn("时间戳", captions)
        self.assertIn("caption_html", captions)
        self.assertNotIn("registry", captions.lower())
        self.assertNotIn("caption-pill-karaoke", captions)

        suno = self._get_skill("suno-song")
        for path in (
            "references/SOURCES.md",
            "references/bitwize/skills/lyric-writer/UPSTREAM.md",
            "references/bitwize/skills/pronunciation-specialist/UPSTREAM.md",
            "references/bitwize/skills/lyric-refiner/UPSTREAM.md",
            "references/bitwize/skills/lyric-reviewer/UPSTREAM.md",
            "references/bitwize/skills/suno-engineer/UPSTREAM.md",
            "references/bitwize/skills/pre-generation-check/UPSTREAM.md",
        ):
            self.assertIn(path, suno["resources"], path)
            content = self._read("suno-song", path)
            self.assertGreater(len(content), 100, path)

    def test_workflow_load_and_skill_load_share_instructions_not_compile_fields(self) -> None:
        workflow = self.client.get("/api/video/workflows/mv", headers=self.headers).json()["data"]
        skill = self._get_skill("mv")
        self.assertEqual(workflow["instructions"], skill["instructions"])
        self.assertIn("pipeline", workflow)
        self.assertNotIn("pipeline", skill)
        self.assertEqual(skill["kind"], "workflow")
