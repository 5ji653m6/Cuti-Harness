# @cuti-ai/tool-video

检查点查询向模型展示检查点 JSON，包括两个版本号、产物摘要和规划要求。提交时将 `base_plan_revision` 对应到 `base_revision`，保留 `base_spec_revision`；不能根据阶段名称猜测版本号。

[English](README.md) | 中文

一组稳定的高层工具，使 DeepSeek agent 能够操作带版本的视频项目，而不暴露 Provider 专用调用。

项目创建和规划必须提供由五个字段组成的视频语言约定。Agent 分别维护界面语言、用户可见创作内容、语音、字幕和 Provider 提示词语言，并在每次计划补丁中保留这些字段。

`video_checkpoint_inspect` 接受 `checkpoint_id="live"`，为执行期间的用户编辑打开规划快照；随后使用返回的 ID 和版本调用 `video_plan_patch_submit`。任务完成/失败通知与主动编辑共用追加、取消路径；只能取消待执行任务，无关的运行中任务继续执行。参见 [Runtime 调度规则](../../../services/video-runtime/README.zh.md)。

修改参数后重试时，提交 `replace_failed_task_ids`，将失败 ID 映射到 `add_tasks` 中的新任务键。Runtime 原子替换待执行的下游任务，保留可复用的已完成产物。失败的持续 Build 可通过 `checkpoint_id="live"` 查看，并保持停止直到修复补丁提交。

明确的编辑请求授权预览后直接执行，无需再次确认。Build 结果区分排队与完成，并指引 Agent 完成依赖步骤。无需 Workflow 的 PlanPatch 能力包含已安装的视频生成与媒体操作；生成片段可在同一计划中接入拼接。

## Model Experience

### 项目视频工具

#### 模型看到什么

[23 个 `video_*` 工具](../../../docs/tool-catalog.zh.md#cuti-aitool-video)提供项目创建、兼容 Cuti 的持续 `PlanPatch` 规划、项目查看、结构化编辑与依赖影响预览、重建执行、持久 Build 控制、产物选择和导出。`video_edit_preview` 只返回费用与受影响步骤，不执行付费操作。schema 不包含 Provider 凭据、内部任务、插件钩子和原始媒体操作。

#### Token 影响

启用工具插件时会产生固定 schema 成本；结果依赖数据，并采用有界摘要。

#### KV Cache 影响

启用的工具集合不变时，前缀保持稳定。

## Known Limitations and Deferred Work

- 首个版本把项目 id 作为显式工具参数；自动把活动项目注入工具参数的功能仍待实现。
