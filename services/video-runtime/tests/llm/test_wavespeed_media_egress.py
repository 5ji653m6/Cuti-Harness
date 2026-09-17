"""WaveSpeedService._resolve_payload_media 只解析媒体字段、不动其他字段，且不真联网。

用 stub 替换 media_egress.resolve_outbound_media_url（方法内是 from-import，运行时按模块属性取，patch 生效）。
用 __new__ 构造实例，避开 __init__ 的 settings 依赖。
"""
from app.llm.wavespeed_service import WaveSpeedService, _finalize_generated_image
from app.llm import wavespeed_service as wavespeed_module
from app.utils import media_egress as me


def _svc():
    return WaveSpeedService.__new__(WaveSpeedService)


async def _tag(url, *, accepts_base64=False):
    return "PUB::" + url


async def test_resolves_str_media_keys(monkeypatch):
    monkeypatch.setattr(me, "resolve_outbound_media_url", _tag)
    svc = _svc()
    payload = {
        "image": "http://localhost:8000/files/a.webp",
        "last_image": "http://localhost:8000/files/b.webp",
        "end_image": "http://localhost:8000/files/c.webp",
        "video": "http://localhost:8000/files/d.mp4",
        "audio": "http://localhost:8000/files/e.mp3",
        "start_image": "http://localhost:8000/files/f.webp",
        "prompt": "a cat",          # 非媒体：不动
        "duration": 5,               # 非媒体：不动
    }
    out = await svc._resolve_payload_media(payload)
    for k in ("image", "last_image", "end_image", "video", "audio", "start_image"):
        assert out[k].startswith("PUB::"), k
    assert out["prompt"] == "a cat"
    assert out["duration"] == 5


async def test_resolves_list_media_keys(monkeypatch):
    monkeypatch.setattr(me, "resolve_outbound_media_url", _tag)
    svc = _svc()
    payload = {
        "images": ["http://localhost:8000/files/1.webp", "http://localhost:8000/files/2.webp"],
        "reference_images": ["http://localhost:8000/files/r.webp"],
        "reference_audios": ["http://localhost:8000/files/r.mp3"],
    }
    out = await svc._resolve_payload_media(payload)
    assert out["images"] == ["PUB::http://localhost:8000/files/1.webp", "PUB::http://localhost:8000/files/2.webp"]
    assert out["reference_images"] == ["PUB::http://localhost:8000/files/r.webp"]
    assert out["reference_audios"] == ["PUB::http://localhost:8000/files/r.mp3"]


async def test_ignores_missing_and_non_str(monkeypatch):
    monkeypatch.setattr(me, "resolve_outbound_media_url", _tag)
    svc = _svc()
    payload = {"image": "", "images": ["", None, 123], "prompt": "x"}
    out = await svc._resolve_payload_media(payload)
    assert out["image"] == ""                 # 空字符串跳过
    assert out["images"] == ["", None, 123]   # 空/None/非字符串原样保留
    assert out["prompt"] == "x"


async def test_non_dict_payload_returned_as_is(monkeypatch):
    monkeypatch.setattr(me, "resolve_outbound_media_url", _tag)
    svc = _svc()
    assert await svc._resolve_payload_media(None) is None


async def test_no_media_keys_is_noop(monkeypatch):
    """T2I/T2V/TTS 这类无媒体 key 的 payload 完全不变。"""
    called = {"n": 0}

    async def counting(url, *, accepts_base64=False):
        called["n"] += 1
        return url

    monkeypatch.setattr(me, "resolve_outbound_media_url", counting)
    svc = _svc()
    payload = {"prompt": "hello", "aspect_ratio": "16:9", "size": "1080p"}
    out = await svc._resolve_payload_media(payload)
    assert out == {"prompt": "hello", "aspect_ratio": "16:9", "size": "1080p"}
    assert called["n"] == 0


async def test_finalize_generated_image_prefers_media_resize(monkeypatch):
    async def resize(**kwargs):
        assert kwargs["image_url"] == "https://provider/image.png"
        assert kwargs["target_width"] == 1920
        assert kwargs["target_height"] == 1080
        return {"result_url": "http://localhost:19004/files/resized.webp"}

    monkeypatch.setattr(wavespeed_module.msc, "image_resize", resize)

    result = await _finalize_generated_image(
        "https://provider/image.png", 1920, 1080,
    )

    assert result == "http://localhost:19004/files/resized.webp"
