import time
import unittest
from unittest.mock import AsyncMock, patch

from app.video_runtime.models import MediaArtifactVersion
from app.video_runtime.builtin_plugins.cuti_provider import CutiAtomicProviderPlugin
from app.video_runtime.security import CapabilityGrant, CapabilityExecutionEnvelope


class ProviderMediaInputTest(unittest.IsolatedAsyncioTestCase):
    def payload(self):
        refs = [MediaArtifactVersion(project_id="p", artifact_id=f"ref:{i}", type=kind,
                 uri=f"https://cdn.example.test/{i}.png")
                for i, kind in enumerate(["source_image", "image", "image", "image"])]
        return {
            "build": {"id": "b"},
            "step": {"step_id": "video", "output_artifact_type": "video",
                     "input_artifact_version_ids": [item.id for item in refs],
                     "parameters": {"prompt": "@图片1 产品，@图片2 人物，@图片3 场景，@图片4 设定", "provider": "seedance-2.5"}},
            # Deliberately different execution/dependency completion order.
            "completed_artifacts": {str(i): refs[i].model_dump(mode="json") for i in [1, 2, 3, 0]},
        }

    async def call(self, payload, capability="api.provider.generate", executor=None):
        grant = CapabilityGrant(project_id="p", session_id="s", user_id="u", plugin_id="cuti.atomic-providers",
            capability=capability, allowed_capabilities=[capability], idempotency_key="stable-key",
            audit_id="a", nonce="n", max_cost_usd=1, timeout_seconds=30, expires_at=int(time.time()) + 60)
        with patch(
            "app.video_runtime.watermark.publish_public_watermark",
            AsyncMock(side_effect=lambda url, generation_id=None: f"{url}?wm=1"),
        ):
            return await CutiAtomicProviderPlugin(executor)._generate(
                CapabilityExecutionEnvelope(grant), payload,
            )

    async def test_direct_provider_receives_all_images_in_agent_order_and_remote_identity(self):
        payload = self.payload()
        payload["step"]["parameters"]["remote_operation_id"] = "existing-job"
        fake = AsyncMock(return_value={"uri": "https://cdn.example.test/out.mp4", "raw_task_id": "existing-job",
                                       "provider_used": "wavespeed", "model": "seedance-2.5",
                                       "model_family": "seedance_2_5"})
        with patch("app.integrations.providers.provider_bridge.generate_video", fake):
            result = await self.call(payload)
        profile = fake.call_args.args[0]
        self.assertEqual(profile["images"], [f"https://cdn.example.test/{i}.png" for i in range(4)])
        self.assertEqual(profile["idempotency_key"], "stable-key")
        self.assertEqual(profile["remote_operation_id"], "existing-job")
        self.assertEqual(profile["provider"], "wavespeed")
        self.assertEqual(profile["model"], "seedance-2.5")
        self.assertEqual(profile["requested_provider"], "seedance-2.5")
        self.assertEqual(result.metadata["resolved_generation_parameters"]["images"], profile["images"])
        self.assertEqual(result.metadata["resolved_generation_parameters"]["model"], "seedance-2.5")
        self.assertEqual(result.metadata["provider_used"], "wavespeed")
        self.assertEqual(result.metadata["model_family"], "seedance_2_5")
        self.assertNotIn("start_image_url", profile)

    async def test_atomic_uses_same_order_and_explicit_id_resolution(self):
        payload = self.payload()
        payload["step"]["parameters"]["images"] = [payload["step"]["input_artifact_version_ids"][0]]
        payload["step"]["parameters"]["generation_mode"] = "i2v"
        fake = AsyncMock(return_value=("job", {"uri": "https://cdn.example.test/out.mp4"}))
        await self.call(payload, "atomic.video.generate", fake)
        task_parameters = fake.call_args.kwargs["task"].parameters
        self.assertEqual(task_parameters["images"],
                         [f"https://cdn.example.test/{i}.png" for i in range(4)])
        self.assertEqual(task_parameters["generation_mode"], "t2v")
        self.assertNotIn("start_image_url", task_parameters)

    async def test_missing_reference_rejected_before_provider(self):
        for change in ("id", "uri", "step", "slot"):
            payload = self.payload()
            if change == "id": payload["step"]["input_artifact_version_ids"].append("absent")
            if change == "uri": payload["completed_artifacts"]["0"]["uri"] = None
            if change == "step": payload["step"]["parameters"]["reference_from_steps"] = ["absent"]
            if change == "slot": payload["step"]["parameters"]["prompt"] = "@图片5"
            with patch("app.integrations.providers.provider_bridge.generate_video", AsyncMock()) as fake:
                with self.assertRaisesRegex(ValueError, "unavailable|no URI|missing images"): await self.call(payload)
                fake.assert_not_called()

    async def test_continuation_keeps_original_references_separate_from_tail(self):
        payload = self.payload()
        tail = MediaArtifactVersion(project_id="p", artifact_id="shot:one:tail",
                                    type="image", uri="https://cdn.example.test/tail.png")
        payload["completed_artifacts"]["tail"] = tail.model_dump(mode="json")
        payload["step"]["input_artifact_version_ids"].append(tail.id)
        payload["step"]["parameters"].update({
            "start_image_from_step": "tail", "reference_from_steps": ["0", "1", "2", "3"],
        })
        fake = AsyncMock(return_value={"uri": "https://cdn.example.test/out.mp4"})
        with patch("app.integrations.providers.provider_bridge.generate_video", fake):
            await self.call(payload)
        profile = fake.call_args.args[0]
        self.assertEqual(profile["start_image_url"], tail.uri)
        # The bridge removes explicit frame URLs from the general input list.
        self.assertEqual([url for url in profile["images"] if url != tail.uri],
                         [f"https://cdn.example.test/{i}.png" for i in range(4)])

    async def test_shared_reference_policy_cannot_degrade_to_text_to_video(self):
        payload = self.payload()
        payload["step"]["input_artifact_version_ids"] = []
        payload["completed_artifacts"] = {}
        payload["step"]["parameters"] = {
            "prompt": "Keep the same hero in every segment",
            "provider": "seedance-2.5",
            "continuity_mode": "shared_reference_images",
        }
        fake = AsyncMock(return_value={"uri": "https://cdn.example.test/out.mp4"})
        with patch("app.integrations.providers.provider_bridge.generate_video", fake):
            with self.assertRaisesRegex(ValueError, "resolved image URI"):
                await self.call(payload)
            fake.assert_not_called()

    async def test_shared_reference_policy_accepts_resolved_artifact_inputs(self):
        payload = self.payload()
        payload["step"]["parameters"]["continuity_mode"] = "shared_reference_images"
        fake = AsyncMock(return_value={"uri": "https://cdn.example.test/out.mp4"})
        with patch("app.integrations.providers.provider_bridge.generate_video", fake):
            await self.call(payload)
        self.assertEqual(len(fake.call_args.args[0]["images"]), 4)

    async def test_audio_video_inputs_and_project_isolation(self):
        payload = self.payload()
        for kind in ("source_audio", "source_video"):
            ref = MediaArtifactVersion(project_id="p", artifact_id=kind, type=kind, uri=f"https://cdn.example.test/{kind}")
            payload["completed_artifacts"][kind] = ref.model_dump(mode="json")
            payload["step"]["input_artifact_version_ids"].append(ref.id)
        fake = AsyncMock(return_value={"uri": "https://cdn.example.test/out.mp4"})
        with patch("app.integrations.providers.provider_bridge.generate_video", fake):
            await self.call(payload)
            self.assertEqual(fake.call_args.args[0]["audios"], ["https://cdn.example.test/source_audio"])
            self.assertEqual(fake.call_args.args[0]["videos"], ["https://cdn.example.test/source_video"])
            fake.reset_mock()
            payload["completed_artifacts"]["0"]["project_id"] = "another-project"
            with self.assertRaises(PermissionError): await self.call(payload)
            fake.assert_not_called()
