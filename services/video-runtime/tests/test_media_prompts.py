from pathlib import Path

from app.chat.v2.media_prompts import MEDIA_PROMPTS_ROOT, media_system_instruction
from app.video_runtime.skills import configured_skill_roots


def test_media_prompts_are_outside_skill_catalog():
    roots = {path.resolve() for path in configured_skill_roots()}
    assert MEDIA_PROMPTS_ROOT.resolve() not in roots
    stages = Path(__file__).resolve().parents[1] / "kit" / "skills" / "stages"
    assert not (stages / "music" / "audio-transcription-director" / "SKILL.md").is_file()
    assert not (stages / "music" / "music-smart-clip-director" / "SKILL.md").is_file()


def test_media_system_instruction_strips_frontmatter():
    text = media_system_instruction("audio-transcription-director")
    assert text.startswith("# Audio Transcription Director")
    assert "Suno word-alignment mode" in text
    clip = media_system_instruction("music-smart-clip-director")
    assert "Keep chorus" in clip
    video = media_system_instruction("video-analyze")
    assert "storyboard[]" in video
    assert "visual_elements[]" in video
    assert "narrative_structure" in video
    assert "facts.content_language" in video
    audio = media_system_instruction("audio-transcription-director")
    assert "facts.content_language" in audio
