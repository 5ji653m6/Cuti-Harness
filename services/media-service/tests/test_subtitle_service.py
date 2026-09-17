import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models.subtitle import SubtitleCue
from app.services import ffmpeg_service, hyperframes_service, subtitle_service


def test_hyperframes_words_fall_back_to_cue_timing_and_preserve_cjk():
    words = hyperframes_service._normalize_words([], [
        {"start": 1.0, "end": 2.0, "text": "你好 world"},
    ])

    assert [item["text"] for item in words] == ["你", "好", "world"]
    assert words[0]["start"] == pytest.approx(1.0)
    assert words[-1]["end"] == pytest.approx(2.0)


def test_hyperframes_authored_html_keeps_llm_words():
    source = (
        "<!doctype html><html><head><style>body{font-size:48px}</style></head>"
        "<body><script>var W = [{\"text\":\"Hello\",\"start\":0,\"end\":1}];</script></body></html>"
    )
    html = hyperframes_service._prepare_authored_html(
        source,
        duration=10.0,
        width=1280,
        height=720,
        accent="#ffcc00",
        has_cjk=False,
    )
    assert "Hello" in html
    assert "font-size:48px" in html
    assert "Cuti CJK" in html


def test_code_composition_accepts_inline_svg_namespaces():
    hyperframes_service._validate_code_composition(
        '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="10" cy="10" r="8" /></svg>'
    )


@pytest.mark.parametrize(
    "html",
    [
        '<img src="https://example.com/a.png">',
        '<script>fetch("/private")</script>',
        '<iframe src="about:blank"></iframe>',
        '<script>window.location="/elsewhere"</script>',
    ],
)
def test_code_composition_rejects_network_and_embedded_content(html):
    with pytest.raises(ValueError, match="HyperFrames composition cannot contain"):
        hyperframes_service._validate_code_composition(html)


def test_code_render_settings_complete_and_override_root_dimensions():
    html = (
        '<main data-composition-id="code-video" data-duration="9" data-fps="60">'
        'Hello</main>'
    )

    normalized = hyperframes_service._apply_code_render_contract(
        html,
        width=1280,
        height=720,
        duration=2,
        fps=24,
    )

    assert 'data-width="1280"' in normalized
    assert 'data-height="720"' in normalized
    assert 'data-duration="2"' in normalized
    assert 'data-fps="24"' in normalized
    assert 'data-duration="9"' not in normalized


def test_authored_html_declares_model_selected_local_font_with_bundled_fallback():
    source = (
        "<!doctype html><html><head><style>"
        'body{font-family:Arial,"Microsoft YaHei",sans-serif}'
        "</style></head><body>你好</body></html>"
    )

    normalized = hyperframes_service._prepare_authored_html(
        source,
        duration=5,
        width=1920,
        height=1080,
        accent=None,
        has_cjk=True,
    )

    assert "font-family:'Microsoft YaHei'" in normalized
    assert "local('Microsoft YaHei')" in normalized
    assert "url('assets/cuti-cjk.ttf')" in normalized


def test_authored_html_does_not_redeclare_existing_font_face():
    source = (
        "<!doctype html><html><head><style>"
        "@font-face{font-family:'Brand';src:local('Brand')}"
        "body{font-family:'Brand',sans-serif}"
        "</style></head><body>Hello</body></html>"
    )

    normalized = hyperframes_service._prepare_authored_html(
        source,
        duration=5,
        width=1920,
        height=1080,
        accent=None,
        has_cjk=False,
    )

    assert normalized.count("font-family:'Brand'") == 2


@pytest.mark.parametrize(
    ("css", "message"),
    [
        (".cap{display:none}", "permanently hidden"),
        (".cap{opacity:0}", "without a reveal timeline"),
    ],
)
def test_hyperframes_rejects_permanently_hidden_authored_captions(css, message):
    source = (
        f"<style>{css}</style>"
        '<div class="cap" data-start="1" data-end="2">字幕</div>'
    )
    with pytest.raises(ValueError, match=message):
        hyperframes_service._prepare_authored_html(
            source,
            duration=3,
            width=1280,
            height=720,
            accent="#ffcc00",
            has_cjk=True,
        )


TOKYO_LYRIC_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<style>
  #lyrics-root{position:relative;width:1920px;height:1080px}
  .lyric{position:absolute;left:50%;bottom:92px}
</style>
</head>
<body>
<div id="lyrics-root" data-composition-id="tokyo-lyrics" data-width="1920" data-height="1080" data-duration="30" data-fps="24">
  <div id="line-1" class="clip lyric" data-start="0" data-duration="4.3" data-track-index="0">你说别回头看　路会自己开</div>
  <div id="line-2" class="clip lyric" data-start="4.34" data-duration="4.24" data-track-index="0">我点点头　把沉默也放开</div>
  <div id="line-3" class="clip lyric chorus" data-start="9.24" data-duration="4.2" data-track-index="0">走吧　走吧　今晚别太慢</div>
  <div id="line-4" class="clip lyric chorus" data-start="13.48" data-duration="4.42" data-track-index="0">走吧　走吧　把夜色带暖</div>
  <div id="line-5" class="clip lyric chorus" data-start="20.36" data-duration="3.94" data-track-index="0">我跟上你的步伐</div>
</div>
<script>var DURATION = 8;</script>
</body>
</html>
"""


def test_hyperframes_authored_html_keeps_clip_durations():
    html = hyperframes_service._prepare_authored_html(
        TOKYO_LYRIC_HTML,
        duration=30.043,
        width=1280,
        height=720,
        accent="#ffbf58",
        has_cjk=True,
    )
    assert 'id="lyrics-root"' in html
    assert 'data-composition-id="tokyo-lyrics"' in html
    assert 'data-duration="30"' in html
    assert 'data-duration="30.043"' not in html
    assert 'data-duration="4.3"' in html
    assert 'data-duration="4.24"' in html
    assert 'data-duration="4.2"' in html
    assert 'data-duration="4.42"' in html
    assert 'data-duration="3.94"' in html
    assert "var DURATION = 8;" in html
    assert 'data-width="1920"' in html
    assert "width:1920px" in html
    assert "你说别回头看" in html
    assert "我跟上你的步伐" in html


def test_hyperframes_authored_html_leaves_demo_frame_and_points_gsap_local():
    source = """<div
      id="highlight"
      data-composition-id="caption-highlight"
      data-start="0"
      data-duration="8"
      data-width="1920"
      data-height="1080"
    >
      <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
      <div id="word-1" class="clip" data-start="1.2" data-duration="2.5" data-track-index="1">Hello</div>
    </div>"""
    html = hyperframes_service._prepare_authored_html(
        source,
        duration=12.5,
        width=1280,
        height=720,
        accent="#00ffcc",
        has_cjk=False,
    )
    assert 'data-duration="8"' in html
    assert 'data-duration="12.500"' not in html
    assert 'data-duration="2.5"' in html
    assert 'data-width="1920"' in html
    assert 'src="assets/gsap.min.js"' in html
    assert "cdn.jsdelivr.net" not in html


def test_hyperframes_wraps_agent_authored_caption_fragment():
    source = """<div class="captions">
      <div class="cue" data-start="2" data-end="4">最近怎么样？</div>
      <div class="cue" data-start="4" data-end="6">我可能得先走。</div>
    </div><style>.cue{display:none}.cue.active{display:inline-block}</style>"""

    html = hyperframes_service._prepare_authored_html(
        source,
        duration=30.176,
        width=1920,
        height=1080,
        accent="#F5C76B",
        has_cjk=True,
    )

    assert "<body>" in html
    assert 'data-composition-id="overlay"' in html
    assert 'data-duration="30.176"' in html
    assert 'class="cue clip"' in html
    assert 'data-start="2" data-end="4" data-duration="2.000"' in html
    assert ".cue.clip{display:inline-block!important}" in html
    assert "最近怎么样？" in html


def test_hyperframes_html_uses_direct_video_audio_and_local_gsap():
    rendered = hyperframes_service._build_html(
        width=1280, height=720, duration=1.0,
        css_vars={"--color-accent": "#00ffcc", "--font-heading": "Cuti CJK", "--color-fg": "#fff"},
        layers=[{"text": "旷野黄金时", "start": 0, "end": 1.0}],
    )

    assert 'src="assets/gsap.min.js"' in rendered
    assert '<video id="source-video"' in rendered
    assert '<audio id="source-audio"' in rendered
    assert "assets/cuti-cjk.ttf" in rendered
    assert 'id="caption-mount"' in rendered
    assert 'data-composition-src="compositions/overlay.html"' in rendered
    assert "#00ffcc" in rendered
    assert "旷野黄金时" in rendered


def test_hyperframes_request_does_not_default_a_caption_style():
    from app.models.subtitle import HyperframesCaptionRequest

    req = HyperframesCaptionRequest(
        video_url="https://example.com/a.mp4",
        run_id="r1",
        caption_html="<!doctype html><html></html>",
    )
    assert req.style is None
    assert req.caption_html.startswith("<!doctype html>")


def test_cuti_template_renderer_has_timed_visible_sentence_animation():
    html = hyperframes_service._build_templated_caption_html(
        width=1280,
        height=720,
        duration=4,
        groups=[{"text": "字幕可见", "start": 1, "end": 3}],
        style="caption-editorial-emphasis",
        accent="#F4C76B",
        position="bottom-safe",
    )

    assert "字幕可见" in html
    assert "tl.set(el,{visibility:'visible'},g.start)" in html
    assert "opacity:1" in html
    assert "display:none" not in html


def test_hyperframes_playbook_bridge_still_loads():
    from app.hyperframes import compose as hf_compose

    data = hf_compose.load_playbook("anime-ghibli")
    css, design = hf_compose.css_from_playbook(data, accent_color="#F6C56A")
    assert data["id"] == "anime-ghibli"
    assert css["--color-accent"] == "#F6C56A"
    assert css["--font-heading"] == "Noto Serif JP"


def test_hyperframes_prefers_complete_sentence_cues():
    groups = hyperframes_service._sentence_groups(
        [{"word": "你", "start": 0.1, "end": 0.2}],
        [{"text": "你好，欢迎回来。", "start": 0.1, "end": 1.4}],
    )

    assert groups == [{"text": "你好，欢迎回来。", "start": 0.1, "end": 1.4}]


def test_hyperframes_word_groups_respect_cue_boundaries():
    words = [
        {"text": "不問", "start": 19.9, "end": 20.2},
        {"text": "身後誰在張望", "start": 20.2, "end": 22.4},
        {"text": "曠野", "start": 22.6, "end": 23.0},
        {"text": "黃金時", "start": 23.0, "end": 23.8},
    ]
    cues = [
        {"text": "不問身後誰在張望", "start": 19.94, "end": 22.44},
        {"text": "曠野黃金時", "start": 22.58, "end": 27.32},
    ]
    groups = hyperframes_service._groups(words, max_words=8, cues=cues)
    texts = ["".join(item["text"] for item in group["words"]) for group in groups]
    assert texts[0].startswith("不問")
    assert "曠野" in texts[-1]
    assert not any("張望曠野" in text for text in texts)


def test_hyperframes_resolves_cli_font_and_browser_from_env(tmp_path, monkeypatch):
    cli = tmp_path / "hyperframes"
    cli.write_text("", encoding="utf-8")
    font = tmp_path / "NotoSansSC-VF.ttf"
    font.write_bytes(b"font")
    chrome = tmp_path / "chrome"
    chrome.write_text("", encoding="utf-8")
    monkeypatch.setenv("HYPERFRAMES_CLI", str(cli))
    monkeypatch.setenv("HYPERFRAMES_CJK_FONT", str(font))
    monkeypatch.setenv("HYPERFRAMES_BROWSER_PATH", str(chrome))

    assert hyperframes_service._resolve_cli() == cli
    assert hyperframes_service._resolve_cjk_font() == font
    assert hyperframes_service._resolve_browser() == chrome


def test_hyperframes_reads_browser_path_file(tmp_path, monkeypatch):
    chrome = tmp_path / "chrome"
    chrome.write_text("", encoding="utf-8")
    pointer = tmp_path / "browser.path"
    pointer.write_text(str(chrome), encoding="utf-8")
    monkeypatch.delenv("HYPERFRAMES_BROWSER_PATH", raising=False)
    monkeypatch.setattr(
        hyperframes_service,
        "BROWSER_CANDIDATES",
        (str(pointer),),
    )

    assert hyperframes_service._resolve_browser() == chrome


def test_hyperframes_cli_missing_raises(monkeypatch):
    monkeypatch.delenv("HYPERFRAMES_CLI", raising=False)
    monkeypatch.setattr(hyperframes_service, "_checkout_hyperframes_cli", lambda start=None: "")
    monkeypatch.setattr(hyperframes_service, "CLI_CANDIDATES", ())
    monkeypatch.setattr(hyperframes_service.shutil, "which", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="HYPERFRAMES_CLI"):
        hyperframes_service._resolve_cli()


def test_hyperframes_cli_walks_checkout_runtime_deps(tmp_path):
    repo = tmp_path / "repo"
    cli = repo / ".runtime-deps/hyperframes/node_modules/hyperframes/bin/hyperframes.mjs"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    nested = repo / "services/media-service/app/services/hyperframes_service.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("", encoding="utf-8")
    other = tmp_path / "other" / "file.py"
    other.parent.mkdir()
    assert hyperframes_service._checkout_hyperframes_cli(nested) == str(cli)
    assert hyperframes_service._checkout_hyperframes_cli(other) == ""


def test_hyperframes_finds_gsap_beside_npm_package_entry(tmp_path):
    cli = tmp_path / "node_modules/hyperframes/bin/hyperframes.mjs"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    gsap = tmp_path / "node_modules/gsap/dist/gsap.min.js"
    gsap.parent.mkdir(parents=True)
    gsap.write_text("", encoding="utf-8")
    assert hyperframes_service._resolve_gsap(cli) == gsap


def test_normalize_cues_wraps_cjk_and_reports_overlap():
    cues, validation = subtitle_service.normalize_cues(
        [
            SubtitleCue(start=0, end=2, text="这是一个用于验证自动换行的字幕句子"),
            SubtitleCue(start=1.8, end=3, text="第二句"),
        ],
        max_lines=2,
        max_chars_per_line=8,
        max_cps=15,
    )

    assert "\n" in cues[0].text
    assert validation["overlaps"] == 1
    assert validation["invalid_cues"] == 0


def test_write_srt_uses_utf8_bom_and_millisecond_timestamps(tmp_path: Path):
    output = tmp_path / "captions.srt"
    subtitle_service.write_subtitle(
        output,
        [SubtitleCue(start=1.234, end=2.5, text="Hello\nworld")],
        "srt",
    )

    text = output.read_text(encoding="utf-8-sig")
    assert "00:00:01,234 --> 00:00:02,500" in text
    assert "Hello\nworld" in text


@pytest.mark.asyncio
async def test_burn_subtitles_builds_safe_ffmpeg_filter(monkeypatch, tmp_path: Path):
    captured = {}

    async def fake_info(_path):
        return {"width": 1920, "height": 1080}

    async def fake_run(command, timeout=None):
        captured["command"] = command
        return 0, "", ""

    monkeypatch.setattr(ffmpeg_service, "get_video_info", fake_info)
    monkeypatch.setattr(ffmpeg_service, "run_ffmpeg", fake_run)
    subtitle = tmp_path / "captions.srt"
    subtitle.write_text("", encoding="utf-8")

    style = await ffmpeg_service.burn_subtitles(
        str(tmp_path / "video.mp4"),
        str(subtitle),
        str(tmp_path / "output.mp4"),
        style_preset="clean",
        position="bottom-safe",
        font_name="Noto Sans CJK SC;unsafe",
    )

    command = captured["command"]
    video_filter = command[command.index("-vf") + 1]
    assert "subtitles=filename=" in video_filter
    assert "original_size=1920x1080" in video_filter
    assert "FontName=Noto Sans CJK SCunsafe" in video_filter
    assert "FontSize=16" in video_filter
    assert "Alignment=2" in video_filter
    assert 40 <= style["font_size"] <= 70
    assert 40 <= style["margin_v"] <= 80
    assert command[-1].endswith("output.mp4")


def test_resolve_subtitle_font_detects_windows_noto_family(monkeypatch):
    original_is_file = Path.is_file

    def fake_is_file(path):
        if str(path).replace("/", "\\").lower().endswith(
            r"windows\fonts\notosanssc-vf.ttf"
        ):
            return True
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    monkeypatch.setattr(ffmpeg_service.settings, "subtitle_font_name", "")
    monkeypatch.setattr(ffmpeg_service.settings, "subtitle_fonts_dir", "")

    family, fonts_dir, source = ffmpeg_service._resolve_subtitle_font()

    assert family == "Noto Sans SC"
    assert fonts_dir.replace("/", "\\").lower().endswith(r"windows\fonts")
    assert source.replace("/", "\\").lower().endswith(r"notosanssc-vf.ttf")


@pytest.mark.asyncio
async def test_burn_subtitles_passes_discovered_fontsdir(monkeypatch, tmp_path: Path):
    captured = {}

    async def fake_info(_path):
        return {"width": 1280, "height": 720}

    async def fake_run(command, timeout=None):
        captured["command"] = command
        return 0, "", ""

    monkeypatch.setattr(ffmpeg_service, "get_video_info", fake_info)
    monkeypatch.setattr(ffmpeg_service, "run_ffmpeg", fake_run)
    monkeypatch.setattr(
        ffmpeg_service,
        "_resolve_subtitle_font",
        lambda _requested=None: ("Microsoft YaHei", r"C:\Windows\Fonts", r"C:\Windows\Fonts\msyh.ttc"),
    )
    subtitle = tmp_path / "captions.srt"
    subtitle.write_text("字幕测试", encoding="utf-8-sig")

    style = await ffmpeg_service.burn_subtitles(
        str(tmp_path / "video.mp4"), str(subtitle), str(tmp_path / "output.mp4")
    )

    video_filter = captured["command"][captured["command"].index("-vf") + 1]
    assert "FontName=Microsoft YaHei" in video_filter
    assert "fontsdir='C\\:/Windows/Fonts'" in video_filter
    assert style["font_name"] == "Microsoft YaHei"
    assert style["fonts_dir"] == r"C:\Windows\Fonts"


def _cjk_subtitle_font_available() -> bool:
    try:
        ffmpeg_service._resolve_subtitle_font()
        return True
    except RuntimeError:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed",
)
@pytest.mark.skipif(
    not _cjk_subtitle_font_available(),
    reason="No CJK subtitle font (install fonts-noto-cjk)",
)
async def test_real_ffmpeg_burn_produces_playable_mp4(tmp_path: Path):
    source = tmp_path / "source.mp4"
    subtitle = tmp_path / "captions.srt"
    output = tmp_path / "captioned.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-shortest", "-c:v", "libx264", "-c:a", "aac", str(source),
    ], check=True, capture_output=True)
    subtitle_service.write_subtitle(
        subtitle,
        [SubtitleCue(start=0.1, end=1.8, text="字幕端到端测试")],
        "srt",
    )

    await ffmpeg_service.burn_subtitles(str(source), str(subtitle), str(output))

    probe = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(output),
    ], check=True, capture_output=True, text=True)
    metadata = json.loads(probe.stdout)
    assert output.stat().st_size > 0
    assert float(metadata["format"]["duration"]) >= 1.9
    assert any(stream.get("codec_type") == "video" for stream in metadata["streams"])
