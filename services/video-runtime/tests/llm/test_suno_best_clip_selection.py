"""单元测试：Suno 多 clip 时长选择（PR-1）

验证 `poll_task_until_complete` 中多 clip 排序：
- has_lyrics / auto_lyrics + target_duration 时，按 |duration - target| 升序顶到 [0]
- 复现用户报障：target=15s，clips=[185s, 69s] → 必须选 69s（偏差 54），而非首条 185s

不依赖 Suno API，通过 monkeypatch 短路 HTTP / S3，直接喂 fake clips 走完末段排序逻辑。

跑：
  conda run -n cuti-video-local pytest tests/llm/test_suno_best_clip_selection.py -v -s
"""
import asyncio
import json
from typing import Any
import pytest

from app.llm.suno_service import SunoService


class _FakeResp:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self._payload = payload
        self._text = json.dumps(payload)

    async def text(self):
        return self._text

    async def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"http {self.status}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self, get_payload: dict):
        self._get_payload = get_payload

    def get(self, url, headers=None, timeout=None):
        return _FakeResp(200, self._get_payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _payload_two_clips(d1_sec: int, d2_sec: int) -> dict:
    """模拟 Suno poll 返回的成功 payload（真实字段：data: [...] 而非 clips）"""
    return {
        "task_id": "f5e0b7dc-3e47-4114-bdba-41b1b0ec2f54",
        "state": "succeeded",
        "data": [
            {
                "clip_id": "aabc3cf1-4ee5-45b1-a9f1-4678916192f0",
                "state": "succeeded",
                "audio_url": "https://example.com/clip1.mp3",
                "video_url": None,
                "title": "轻快切换",
                "tags": "Warm rhythmic pop bumper",
                "lyrics": "[Instrumental]",
                "duration": d1_sec,
                "image_url": "https://example.com/clip1.jpg",
                "created_at": "2026-05-10T07:13:34.026Z",
                "mv": "chirp-v4-5",
            },
            {
                "clip_id": "c981d701-a93e-4d02-b391-15b3e0c6ef9b",
                "state": "succeeded",
                "audio_url": "https://example.com/clip2.mp3",
                "video_url": None,
                "title": "轻快切换",
                "tags": "Warm rhythmic pop bumper",
                "lyrics": "[Instrumental]",
                "duration": d2_sec,
                "image_url": "https://example.com/clip2.jpg",
                "created_at": "2026-05-10T07:13:34.026Z",
                "mv": "chirp-v4-5",
            },
        ],
    }


@pytest.fixture(autouse=True)
def _patch_s3_and_http(monkeypatch):
    """避开 S3 上传与真实 HTTP，让 poll_task_until_complete 拿到 fake payload 后直接走完后段。"""
    # S3 上传：原样返回输入 url，避免真实下载 / 上传
    async def _fake_dl_up(url: str, generation_id: str = ""):
        return url

    monkeypatch.setattr(
        "app.llm.suno_service.s3_utils.download_and_upload_audio_to_s3",
        _fake_dl_up,
    )

    # tenacity retry 装饰器在 poll 上仅捕 SunoRetryException；这里走的是 succeeded 路径，无需 retry。

    yield


def _make_session_factory(payload: dict):
    """用作 aiohttp.ClientSession 的替身：返回我们造的 fake session。"""
    def _factory(*a, **kw):
        return _FakeSession(payload)
    return _factory


@pytest.mark.asyncio
async def test_best_clip_pick_shorter_when_target_short(monkeypatch):
    """target=15s, clips=[185s, 69s]：必须选 69s（偏差 54s）。

    复现用户上报场景：之前总是 clips[0]=185s（偏差 170s）被选，应改为按偏差升序。
    """
    payload = _payload_two_clips(d1_sec=185, d2_sec=69)
    monkeypatch.setattr("app.llm.suno_service.aiohttp.ClientSession", _make_session_factory(payload))

    svc = SunoService(api_key="dummy")
    result = await svc.poll_task_until_complete(
        task_id="f5e0b7dc-3e47-4114-bdba-41b1b0ec2f54",
        original_prompt="bumper",
        generation_params={
            "has_lyrics": False,
            "auto_lyrics": True,
            "target_duration": 15,
            "prompt": "bumper",
            "custom_mode": False,
            "make_instrumental": False,
            "tags": "Ultra short, Bumper",
            "vocal_gender": None,
        },
    )

    assert result.success is True
    assert result.clips_count == 2
    assert result.clips[0].duration == 69, "best clip 应是 69s（偏差 54）而不是 185s（偏差 170）"
    assert result.clips[1].duration == 185
    assert result.message and "已自动选择偏差最小" in result.message
    assert "69" in result.message and "偏差54" in result.message


@pytest.mark.asyncio
async def test_best_clip_pick_first_when_already_minimal(monkeypatch):
    """target=180s, clips=[178s, 195s]：178s 偏差 2，195s 偏差 15 —— best=178s 在原 [0] 位置不动。"""
    payload = _payload_two_clips(d1_sec=178, d2_sec=195)
    monkeypatch.setattr("app.llm.suno_service.aiohttp.ClientSession", _make_session_factory(payload))

    svc = SunoService(api_key="dummy")
    result = await svc.poll_task_until_complete(
        task_id="t-178-195",
        original_prompt="standard track",
        generation_params={
            "has_lyrics": True,
            "auto_lyrics": False,
            "target_duration": 180,
            "prompt": "lyrics body",
            "custom_mode": True,
            "make_instrumental": False,
            "tags": None,
            "vocal_gender": None,
        },
    )

    assert result.success is True
    assert result.clips[0].duration == 178
    assert result.clips[1].duration == 195


@pytest.mark.asyncio
async def test_best_clip_no_target_duration_keeps_order(monkeypatch):
    """无 target_duration 时不重排，保留 Suno 返回顺序。"""
    payload = _payload_two_clips(d1_sec=200, d2_sec=120)
    monkeypatch.setattr("app.llm.suno_service.aiohttp.ClientSession", _make_session_factory(payload))

    svc = SunoService(api_key="dummy")
    result = await svc.poll_task_until_complete(
        task_id="t-no-target",
        original_prompt="bgm only",
        generation_params={
            "has_lyrics": False,
            "auto_lyrics": False,
            "target_duration": None,
            "prompt": "bgm",
            "custom_mode": False,
            "make_instrumental": True,
            "tags": None,
            "vocal_gender": None,
        },
    )

    assert result.success is True
    assert result.clips[0].duration == 200, "纯 BGM 无 target_duration 时不重排"
    assert result.clips[1].duration == 120
    # 无 target_duration 不会注入 "已自动选择偏差最小" 文案；只会得到 success_result_with_clips 的默认信息
    assert "已自动选择偏差最小" not in (result.message or "")
    assert "偏差" not in (result.message or "")


@pytest.mark.asyncio
async def test_best_clip_only_one_clip_works(monkeypatch):
    """只返回 1 个 clip 时仍走通；message 给出偏差信息。"""
    payload = {
        "task_id": "t-1clip",
        "state": "succeeded",
        "data": [
            {
                "clip_id": "single",
                "state": "succeeded",
                "audio_url": "https://example.com/only.mp3",
                "duration": 90,
                "lyrics": "[Verse]\nfoo",
            }
        ],
    }
    monkeypatch.setattr("app.llm.suno_service.aiohttp.ClientSession", _make_session_factory(payload))

    svc = SunoService(api_key="dummy")
    result = await svc.poll_task_until_complete(
        task_id="t-1clip",
        original_prompt="lyrics body",
        generation_params={
            "has_lyrics": True,
            "auto_lyrics": False,
            "target_duration": 60,
            "prompt": "lyrics",
            "custom_mode": True,
            "make_instrumental": False,
            "tags": None,
            "vocal_gender": None,
        },
    )

    assert result.success is True
    assert result.clips_count == 1
    assert result.clips[0].duration == 90
    assert result.message and "偏差30" in result.message


@pytest.mark.asyncio
async def test_suno_keeps_ingested_storage_url_not_vendor(monkeypatch):
    """Local/open-source must persist /files (or dest CDN), not files.aimusicapi.ai."""
    async def _ingest(url: str, generation_id: str = ""):
        return f"http://localhost:8001/files/audios/{generation_id or 'clip'}.mp3"

    monkeypatch.setattr(
        "app.llm.suno_service.s3_utils.download_and_upload_audio_to_s3",
        _ingest,
    )
    payload = _payload_two_clips(d1_sec=15, d2_sec=16)
    monkeypatch.setattr(
        "app.llm.suno_service.aiohttp.ClientSession",
        _make_session_factory(payload),
    )
    svc = SunoService(api_key="dummy")
    result = await svc.poll_task_until_complete(
        task_id="keep-stored",
        original_prompt="instrumental",
        generation_params={
            "has_lyrics": False,
            "auto_lyrics": False,
            "target_duration": None,
            "prompt": "instrumental",
            "custom_mode": True,
            "make_instrumental": True,
            "tags": "synth",
            "vocal_gender": None,
        },
    )
    assert result.success is True
    assert all(
        clip.audio_url.startswith("http://localhost:8001/files/audios/")
        for clip in result.clips
    )
    assert all("example.com" not in clip.audio_url for clip in result.clips)


@pytest.mark.asyncio
async def test_null_clip_duration_does_not_crash(monkeypatch):
    """Suno succeeded + audio_url with duration:null must not TypeError on +=."""
    payload = {
        "task_id": "t-null-duration",
        "state": "succeeded",
        "data": [
            {
                "clip_id": "null-dur-1",
                "state": "succeeded",
                "audio_url": "https://example.com/ready.mp3",
                "duration": None,
                "lyrics": "",
                "title": "streaming",
            },
            {
                "clip_id": "null-dur-2",
                "state": "succeeded",
                "audio_url": "https://example.com/ready2.mp3",
                "duration": None,
                "lyrics": "",
            },
        ],
    }
    monkeypatch.setattr(
        "app.llm.suno_service.aiohttp.ClientSession",
        _make_session_factory(payload),
    )
    svc = SunoService(api_key="dummy")
    result = await svc.poll_task_until_complete(
        task_id="t-null-duration",
        original_prompt="instrumental",
        generation_params={
            "has_lyrics": False,
            "auto_lyrics": False,
            "target_duration": None,
            "prompt": "instrumental",
            "custom_mode": True,
            "make_instrumental": True,
            "tags": "synth",
            "vocal_gender": None,
        },
    )
    assert result.success is True
    assert result.clips_count == 2
    assert result.clips[0].duration == 0
    assert result.clips[1].duration == 0
