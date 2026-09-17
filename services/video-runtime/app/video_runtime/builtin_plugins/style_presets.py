from __future__ import annotations

from ..plugins import BaseVideoPlugin, PluginContext


class StylePresetPlugin(BaseVideoPlugin):
    """Applies portable prompt defaults before a workflow compiles its plan."""

    PRESETS = {
        "cuti.cinematic": "cinematic composition, coherent lighting, production-quality detail",
        "cuti.anime": "polished anime film style, clean line art, consistent character design",
        "cuti.documentary": "natural documentary cinematography, realistic texture, restrained grading",
    }

    async def before_plan(self, context: PluginContext) -> None:
        spec = context.values.get("video_spec")
        if spec is None:
            return
        prefix = self.PRESETS.get(spec.style_id)
        if not prefix:
            return
        for shot in spec.shots:
            if not shot.visual_prompt.startswith(prefix):
                shot.visual_prompt = f"{prefix}. {shot.visual_prompt}"
