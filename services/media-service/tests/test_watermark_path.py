from app.config import resolve_watermark_image_path, get_settings


def test_resolve_watermark_default_asset():
    path = resolve_watermark_image_path("assets/watermark.png")
    assert path is not None
    assert path.endswith("watermark.png")


def test_resolve_watermark_empty_disabled():
    assert resolve_watermark_image_path("") is None
    assert resolve_watermark_image_path("   ") is None


def test_settings_default_watermark_path():
    get_settings.cache_clear()
    assert get_settings().watermark_image_path == "assets/watermark.png"
    get_settings.cache_clear()
