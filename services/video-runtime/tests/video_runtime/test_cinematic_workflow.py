from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from app.video_runtime.skills import VideoSkillRuntime
from app.video_runtime.models import MediaArtifactVersion
from app.video_runtime.plugins import PluginContext
from app.video_runtime.workflow_plans import compile_skill_workflow
from app.video_runtime.staged_planning import _planning_family
from app.integrations.providers import provider_bridge as bridge
from test_workflow_plan_snapshots import _spec


def test_cinematic_catalog_and_continuation_plan():
    skills = VideoSkillRuntime()
    view = next(item for item in skills.prompt_view() if item['name'] == 'cinematic')
    assert view['available']
    workflow = skills.workflows.get('cinematic')
    assert _planning_family(workflow, 'cinematic') == 'direct'
    source = MediaArtifactVersion(project_id='p', artifact_id='identity', type='source_image',
                                  uri='https://cdn.example.test/identity.png')
    spec = _spec('cinematic', source_asset_ids=['identity'])
    spec.shots[1].transition = 'continuous'
    plan = compile_skill_workflow(workflow, PluginContext(project_id='p', values={
        'base_project_version_id': 'v1', 'source_artifacts': {'identity': source},
    }), spec)
    clips = [item for item in plan.items if item.capability == 'atomic.video.generate']
    tail = next(item for item in plan.items if item.capability == 'media.extract_frame')
    assert clips[1].parameters['reference_from_steps'] == [*clips[0].parameters['reference_from_steps'], tail.step_id]
    assert tail.step_id in clips[1].depends_on
    assert tail.depends_on == [clips[0].step_id]
    for clip in clips:
        assert clip.parameters['reference_mode'] == 'multi_reference'
        assert 'start_image_from_step' not in clip.parameters
        assert clip.parameters['generate_audio'] is True


@pytest.mark.asyncio
async def test_cinematic_sends_identity_and_tail_to_multireference_endpoint(monkeypatch):
    create = AsyncMock(return_value='task')
    service = SimpleNamespace(create_seedance_2_t2v_task=create,
        poll_seedance_video_task_until_complete=AsyncMock(return_value=SimpleNamespace(video_url='https://cdn/out.mp4')))
    monkeypatch.setattr(bridge, '_resolve_media_urls', AsyncMock(side_effect=lambda urls: urls))
    monkeypatch.setattr('app.llm.wavespeed_service.get_wavespeed_service', lambda: service)
    profile = bridge.normalize_video_profile({
        'model': 'seedance-2.0', 'reference_mode': 'multi_reference',
        'prompt': '@图片2为上一段首帧，参考动作',
        'images': ['https://cdn/identity.png', 'https://cdn/tail.png'],
    })
    assert 'start_image_url' not in profile
    await bridge._wavespeed_generate(profile)
    assert create.call_args.kwargs['reference_images'] == profile['images']
    assert 'image' not in create.call_args.kwargs
    with pytest.raises(ValueError, match='multi_reference'):
        bridge.normalize_video_profile({**profile, 'start_image_url': 'https://cdn/tail.png'})
