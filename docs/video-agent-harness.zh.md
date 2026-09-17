# Cuti Video Harness 参考

[English](video-agent-harness.md) | 中文

本文档定义基于 DeepSeek Harness 构建的视频专用层的职责、存储、扩展与执行规则。

## 组件职责

| 组件 | 归属 | 职责 |
|---|---|---|
| Session、提示词、模型调用、agent loop、工具选择 | Cuti Harness | 理解意图并选择一个面向模型的视频工具。 |
| `@cuti-ai/tool-video` | Cuti Harness 插件 | 暴露 11 个项目级操作，不向模型暴露 Provider 或工作流内部细节。 |
| Video Runtime HTTP Provider | Cuti Harness 插件 | 将取消信号及可信的 Session／用户身份转发到 Python 进程。 |
| Video Runtime | Cuti Python 运行时 | 管理项目、版本、产物、依赖、重建、校验、时间线、导出和有序事件。 |
| Video Studio | Cuti React 应用 | 展示聊天、可验证的 agent 与 Build 进度、产物、播放、时间线编辑、重建影响、费用、校验和版本历史。 |

Video Runtime 是视频项目状态的唯一事实来源。一个 Harness Session 可以绑定多个项目，一个项目也可以绑定多个 Session。删除或压缩 Session 不会删除项目产物。

## 增量构建模型

`ProjectVersion` 是一份不可变选择清单：每个逻辑产物选择一个 `ArtifactVersion`，并可选择一个时间线产物。`ArtifactEdge` 从输入版本指向依赖它的输出版本，并指定 `hard`、`validate`、`soft` 或 `none` 失效策略。

`video_change_preview` 针对一个基础作品版本记录 `ChangeRequest`，再以确定性算法把当前依赖图划分为重建、校验和复用集合，同时给出拓扑排序后的重建顺序与费用估算。`video_rebuild_apply` 必须携带预览使用的基础版本和幂等键。并发任务基于过期版本时会收到 HTTP 409。

`VideoBuildRuntime.execute_build` 使用稳定的逐产物幂等键调用 Provider／工作流适配器，校验计划指定的产物和新生成产物，并在一个数据库事务中提交全部替换结果。失败时旧作品版本继续有效；再次执行已完成的 Build 会返回已经提交的版本。

## 首次视频构建

`video_project_create`、`video_project_plan` 与 `video_project_build` 增加首次构建路径，但不会增加第二套 Agent Loop。Cuti Harness 生成与 Provider 无关的 `VideoSpec`；Workflow Plugin 把它编译为与增量和导出任务共用的持久化 `BuildPlan`。计划包含稳定步骤身份、Capability、依赖、幂等键、输出产物身份和预计成本。

可选 Workflow Skill（`seedance2`、`mv`、`short-drama-workflow`、`cuti-product-workflow`、`cuti-scenario-product-workflow`）把 `VideoSpec` 编译成这份 `BuildPlan`。每个成功步骤立即保存为 draft，服务重启后可直接复用。只有全部媒体与校验步骤通过后，活动 ProjectVersion 才会切换。

`cuti.atomic-providers` 复用 Cuti 的图片、音乐与 Seedance Provider；`cuti.media-core` 复用 Cuti 的 TTS、Media Service 与 FFmpeg 操作；`cuti.continuity-validator` 始终检查时间线和媒体结构，并探测最终视频是否可解码、时长及音轨，也可选择启用 Cuti 已有的 VLM 视频一致性校验。对已经组装完成的不可变版本，MP4 导出是持久化零拷贝导出；格式转换仍作为 Export Build 执行。

## 插件模型

插件目录包含 `video-plugin.yaml` 和 Python 入口。manifest 声明 API 与数据版本、Capability、Workflow、Style、Validator、Media Operator、Skill 依赖、插件依赖、网络与凭据要求、沙箱要求、费用上限，以及可选的 Cordis 或前端扩展。

运行时调用 `on_load`、Plan 钩子、执行钩子、产物校验与提交钩子、`migrate` 和 `on_unload`。`VIDEO_PLUGIN_PATHS` 将发现范围限制在明确配置的目录。受信任的内置插件可以进程内运行；不受信任的插件声明沙箱镜像、入口和超时，其模块不会被导入 Runtime 进程，而是由导入的 Cuti Sandbox Worker 执行插件包。

只包含说明的 Skill 仍可单独安装。只有当 Skill 提供可执行代码、Provider、校验、迁移或其他运行时生命周期行为时，才需要成为插件 bundle。

整个进程只拥有一个 `VideoSkillRuntime`，统一处理说明型 Skill、Director Skill、可执行 Capability Skill 和 Workflow Skill。它发现 `skills/system`、`skills/builtin`、`skills/external` 和 `kit/skills/stages`，通过同一个 `SkillCatalog` 预先校验元数据并按需读取正文和可执行契约。Workflow Registry 校验 pipeline 权限、Capability 名称和 Skill 依赖，再由 `cuti.skill-workflows` 将声明暴露为 Workflow Plugin。BFF 将这份 Catalog 提供给现有 Cuti Skill 前端，接收 `workflow_id` 与 `activated_skill_ids`，在 Video Runtime 中持久化长期 `ProjectSkillLock`，并在安全 ZIP 安装后统一重载 Runtime。Build 保存前，Runtime 会统一解析所选 Workflow、Workflow 依赖、显式启用的 Skill、每步 Director Skill、项目锁定 Skill 和 Capability 绑定 Skill。每个 `BuildStep` 冻结 Skill 身份、版本、完整文件哈希、角色、Hook 和实际指令，并在制作进度中展示解析到的 Skill 名称；Provider 提示词使用这份冻结上下文，Artifact 同时记录来源。必需 Skill 缺失或停用时会明确失败，不会退回固定目录读取。`/api/video/workflows` 提供最终生效的 Workflow 目录。

## 执行授权

Cuti Harness 的工具管线负责授权 11 个面向模型的操作。所有在 Video Runtime 注册的嵌套 Provider、Skill 脚本、沙箱操作和媒体操作都通过 `RuntimeCapabilityRegistry` 与 `CapabilityExecutionGateway` 执行。

网关校验短期有效的 HMAC 签名 Grant，身份包含项目、Session、用户、插件和 Capability。Grant 还限制网络域名、费用、超时、并发、重试、幂等、审计身份和取消身份。插件不能把 Grant 扩大到自身 manifest 之外，操作在访问网络前还必须显式校验目标域名。

## HTTP API

API 根路径是 `/api/video`。它提供项目创建与查看、已安装插件和生效工作流列表、首次构建计划持久化与读取、Build 启动／读取／取消／恢复、逐步骤与校验状态、变更预览、重建提交、产物版本选择、固定作品版本导出、作品版本列表／恢复和项目事件流。修改操作支持幂等。事件使用项目内单调递增序号，并接受 `after` 参数用于重连。

迁移期间，组合式 Cuti 应用继续提供已导入的 `/chat-v1/service/v2` 与 `/chat-v1/service/studio` API。设置 `VIDEO_AGENT_BACKEND=deepseek` 时，兼容 BFF 会保留核心 `/chat-v1/service/v2` Run、消息、事件、取消、产物选择和用量路径，同时把请求转换为 Harness Session RPC 与 Video Runtime 状态。它会向 Video Studio 进度视图投影回答文本、模型身份与 Token 用量、决策步骤边界、具名工具输入与结果、终止状态和 Runtime Build 步骤，但不会投影私有推理或系统指令。项目没有产物或 Build 时，后续消息会收到自动依次执行 `video_project_plan` 与 `video_project_build` 的指令；已有作品的项目继续使用对话式编辑行为。历史 Harness Session 已删除的项目仍会以空对话历史出现在 Run 列表中，因此一条孤立绑定不会隐藏其他项目。独立 Video Runtime 也会挂载相同的兼容路由，供本地部署使用。

## 运行时选择

`VIDEO_AGENT_BACKEND` 只接受 `deepseek`。产品启动会挂载 Harness 兼容 BFF、加载已配置 Video Plugin 和 Skill Workflow，并向 `VideoBuildRuntime` 提交结构化 Workflow 或 RebuildPlan。Cuti Harness 是唯一的规划循环；Provider 工具不会启动第二个 Planner。`VIDEO_INCREMENTAL_ENGINE_ENABLED` 仍作为规范化项目存储的兼容部署开关且默认开启；新路径不能关闭插件分发。

导入的 Cuti 媒体服务继续提供 Provider 和媒体实现代码，但其中依赖 Skill 的提示词也通过同一个进程级 Catalog 解析，不再直接读取固定 stage 目录。

## 当前集成状态

仓库包含 Cuti Harness 工具组合、项目运行时、真实 Postgres 迁移、增量执行器、插件生命周期、授权网关、兼容 BFF、Cuti 原子 Provider 适配器、隔离 Sandbox Worker 和 Video Studio 项目界面。Create 工作区用同一套通用 Artifact 渲染逻辑处理 Provider 直调和完整视频流水线。Runtime 的 draft 与已选版本会自动分类为文档、故事、图片、视频、音频或其他产物；最新图片或视频会置顶，视频卡片支持取帧。该工作区不包含专用 `VideoResultsPanel`，也不请求旧的 thread 聚合接口。独立服务支持 Bearer Token 身份适配，本地自托管使用 `local-user`；生产部署只需注入真实 Provider 凭据和部署专用密钥，源码不保存这些秘密。

本地自托管使用 `ACCOUNT_BACKEND=env`，直接从 `OPENAI_API_KEY`、`WAVESPEED_API_KEY`、`SUNO_API_KEY` 及其他可选 Provider 环境变量读取账号。`deploy/compose.video.yml` 已启用内置插件目录、导入的 Media Service，以及由 Video Runtime 在 `/files` 提供的共享本地媒体卷；本地配置不要求 S3 凭据。Compose 使用的 Capability Grant 密钥仅供本地开发，生产部署必须替换。可以直接向 Compose 提供仓库外的私有环境文件而不复制秘密，例如 `docker compose --env-file ../cuti-video-agent/.env -f deploy/compose.video.yml up`。Windows 使用本机 HTTP 代理时，还要给 Node 版 Cuti Harness 进程传入 `HTTP_PROXY`、`HTTPS_PROXY` 和 `NODE_USE_ENV_PROXY=1`；否则可能出现 Python Provider 可用、Harness 模型请求却超时的现象。

迁移与仓库重启路径已在本地 PostgreSQL 上验证。一次真实的低成本 GPT Image + Seedance 构建已继续完成尾帧提取、时间线组装、FFprobe 校验、原子 `ProjectVersion` 提交、MP4 零复制导出、Cuti Harness 工具调用和 Video Studio 可播放预览。导入的 Video Studio 仍保留既有 lint 债务；迁移新增前端文件检查通过，生产构建成功。Skill 列表、项目启用、结构化选择和 ZIP 安装现在均使用 Video Runtime BFF；其他无关的旧管理路由只保留在导入的兼容应用中。
