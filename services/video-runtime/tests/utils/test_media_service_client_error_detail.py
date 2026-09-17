import httpx
import pytest

from app.utils import media_service_client


@pytest.mark.asyncio
async def test_media_service_error_preserves_renderer_detail(monkeypatch):
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"detail": "font_family_without_font_face: Microsoft YaHei"},
        )

    client = httpx.AsyncClient(
        base_url="http://media.test",
        transport=httpx.MockTransport(respond),
    )
    monkeypatch.setattr(media_service_client, "_client", client)
    try:
        with pytest.raises(RuntimeError, match="font_family_without_font_face: Microsoft YaHei"):
            await media_service_client._post("video/hyperframes/render", {})
    finally:
        await client.aclose()
