---
name: language-zh
description: Keep one agent run's user-visible output, spoken narration or dialogue, and requested on-screen copy in Simplified Chinese. Use when the user invokes $language-zh or $zh.
metadata:
  kind: language
  version: "0.1.0"
  roles: [guidance, stage_supervisor]
  scope:
    type: run
  hooks: [before_stage, after_stage]
  language:
    code: zh-CN
    aliases: [zh]
---

# 中文语言契约

在本次运行的所有阶段保持以下语言选择：

- 用户可见的回复、计划、任务标题、摘要、脚本、镜头规划和审查报告使用简体中文。
- 视频原生生成的旁白或对白使用普通话；跨片段继续沿用同一声音设定。
- 只有在内容本身需要画面文字或字幕时，才使用简体中文；不要因此强制添加文字或字幕。
- 品牌名、型号、代码、JSON 键、能力 ID、模型 ID 和其他机器标识保持原样。
- 供应商 Prompt 使用最适合当前模型与工作流的语言。旧版 `seedance2` 工作流仍可使用中文生成 Prompt，并在 Prompt 中明确要求中文语音。

该选择持续到当前运行结束，或用户显式切换到另一个语言 Skill。不要改写已经完成的产物。
