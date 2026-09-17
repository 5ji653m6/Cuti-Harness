# agent_config — MV 管线后端策略配置

按 **配置轴** 组织，不要把无关字段塞进同一个 Profile 类。

## 配置轴

| 轴 | 模块 | 键 | 本期 |
|----|------|-----|------|
| global_defaults | `tool_enums.DefaultValues` | — | 定义仍在 `tool_enums`；`agent_config` 包入口 re-export |
| engine | `transcription` | `hybrid` / `gemini` | granularity 等 |
| video_tool | `video_tool_profiles` + `duration` | `VideoGenerationTool` | scene_split；秒数从 wrapper 链求交 |

## 单一事实来源

- **API 整数秒**：`video_tool_wrapper` / `lipsync_tool_wrapper` 链上 `supported_duration_seconds`
- **规划秒数列表**：`duration` 对用户链求交（或 None 时全产品 fallback）
- **拆场景阈值**：`video_tool_profiles.scene_split_threshold_sec`（可 ≠ min(秒数)）
- **音乐切分粒度**：`transcription` 按转录 method，与视频模型正交

## 对外入口

业务代码优先：

```python
from app.agent_config import (
    get_audio_driven_duration_values,
    get_audio_driven_split_threshold,
    get_audio_segment_granularity_for_method,
    ...
)
```

## 加新配置前

1. 键是 engine / video_tool / image_tool / global 哪一种？
2. 能否从 wrapper 链推导？能 → 只改 `_i2v`，不进 profile。
3. 是否用户可见？是 → `UserOption`；否 → 本包 profile 或 engine 表。
