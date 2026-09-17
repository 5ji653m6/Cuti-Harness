# 视频生成底部进度（`generation_todo`）与可编排 Workflow — 现状与改造方案

> 文档目的：回答「后端会不会传 `generation_todo` / `completed_steps`」「是否虚拟」「谁插入」「VideoAgent 还是 VideoChatAgent」；并基于现状给出**动态 Workflow（含 Music 节点位置）**的改造方案。  
> **范围**：以仓库内 `cuti-front-end-lovable`、`Cuti-VideoChatAgent`、`Cuti-VideoAgent` 代码为准（2026-04 快照）。

---

## 1. `generation_todo` 是什么？后端会传吗？

### 1.1 结论

| 问题 | 结论 |
|------|------|
| 后端 `MessageType` 里有没有 `generation_todo`？ | **没有**。在 `Cuti-VideoChatAgent/storybook_app/services/agent/base_agent.py` 的 `MessageType` 枚举中不存在该类型。 |
| Python 服务里是否检索到 `generation_todo` 字符串？ | **没有**（`Cuti-VideoChatAgent/storybook_app` 与 `Cuti-VideoAgent` 业务代码中无此事件名）。 |
| 那用户看到的「底部进度条」数据从哪来？ | **前端构造的一条「合成消息」**：`event_type: "generation_todo"`，放在会话消息列表里，但**不出现在聊天气泡流里**（`MessageArea` 里对 `displayMessages` 过滤掉了 `generation_todo`，只用于底部 **Sticky Todo**）。 |

因此：**`generation_todo` 对后端而言不是一等持久化事件类型**；它是前端的 **UI 聚合载体**，用来挂 `run_id`、`status`、各类 progress 数字等。

### 1.2 VideoAgent vs VideoChatAgent

两者都复用同一套 **`base_agent.MessageType`** 与 **`GENERATED_EVENTS` / `PROGRESS_EVENTS`**（见 `stream_service.py`）。**都不会单独发送 `generation_todo`**。区别在对话/路由能力，而不是「是否多一种 todo 事件」。

---

## 2. 「虚拟」是什么意思？

在本文语境下指：

1. **不是后端 SSE 里一个叫 `generation_todo` 的独立事件**（与 `video_analysis`、`music_generated` 等不同）。
2. **由前端在内存（及刷新后重建）中插入/更新**，用来驱动 UI。
3. **与 DB 的关系**：若某次实现把整条消息持久化进 `conversation_messages`，那是产品/实现细节；当前代码路径里核心是 **前端合成 + 用其它真实事件的 `event_type` 推断步骤完成度**。

---

## 3. 什么时候会插入 / 更新？谁操作？

### 3.1 插入 `generation_todo` 的主要时机（`CreateVideoPage.tsx`）

1. **`user_input` 且 `has_confirmed === true`**  
   在流里处理 `user_input` 时，若当前 `run_id` 还没有对应 todo，则 **push 一条** `generation_todo`（含 `status: "running"` 等初始字段）。

2. **各类 progress 事件**（`video_generation_progress`、`keyframe_*`、`music_generation_progress` 等）  
   若列表里**还没有** `generation_todo`，会在 **最近一条 `user_input` 之后** splice 插入一条，再合并 `event_data`（保证进度条能显示）。

3. **`rebuildGenerationTodo`（刷新/合并会话详情后）**  
   当任务仍在 `running` / `queued` / `interrupted` 等，且满足「需要重建」条件时，根据**已拉取的消息列表**拼出一条 `generation_todo`，并写入 **`completed_steps`**（见下一节）。

4. **占位**  
   仅有 `tasks.running`、但还没有 `user_input` 消息时，可插入带 `todo_pending_user_input: true` 的占位 todo（避免列表空窗）。

以上全部是 **前端 React 状态 `conversationMessagesMap` 的逻辑**，不是用户手工点的独立接口。

---

## 4. `generation_todo.event_data.completed_steps` 后端会带吗？

### 4.1 结论

- **正常运行时 SSE 合并 todo**：代码在更新 `generation_todo` 时主要是 **spread 旧 `event_data` + 覆盖 progress 字段**，**不会**从服务端收到一个专门的 `completed_steps` 数组再写进去（因为根本没有这类后端事件）。
- **显式赋值 `completed_steps` 的路径**：主要在 **`rebuildGenerationTodo`**：前端扫描 `processedMessages`，把出现在「约定列表」里的 `msg.event_type` 收集进 `Set`，再 `Array.from(completedSteps)` 赋给 `event_data.completed_steps`。

### 4.2 `MessageArea` 里怎么用

`hasAnyOrCompleted` 逻辑：

1. 若 `completed_steps` **非空**，且其中包含某步所需的事件名之一 → 该步算 **done**；
2. 否则退化为：当前会话所有消息的 `event_type` 集合里是否出现过这些事件（与 `completed_steps` 在重建场景下通常一致）。

因此：**`completed_steps` 是前端为「恢复/对齐」准备的冗余字段，不是后端契约字段**（除非你们未来在 DB 里持久化整条 `generation_todo` 并带上它）。

---

## 5. 当前底部 7 步与后端事件的对应（定死在前端）

以下摘自 `MessageArea.tsx` 中 **`steps` 数组**（顺序固定）：

| 顺序 | `id` | 「完成」所依赖的 `event_type`（任一即可，除非特别说明） |
|------|------|----------------------------------------------------------|
| 1 | `analysis` | `video_analysis` |
| 2 | `story_style` | `story_outline_generated` |
| 3 | `visual` | `characters_designed` |
| 4 | `scenes` | `scenes_generated` **或** `storyboard_detail_generated` |
| 5 | `storyboards` | `keyframes_generated`，且若反思未完成则不算完成（见代码） |
| 6 | `shots` | `video_segments_generated` |
| 7 | `final` | `video_completed` |

**Music**：`base_agent` 有 `music_generated`、`music_generation_progress`，但 **上述 7 步没有任何一步** 以 `music_generated` 为完成条件；`rebuildGenerationTodo` 里的 `eventTypeOrder` 虽包含 `music_generated`，**仅用于填充 `completed_steps` 集合**，**不改变** `MessageArea` 的 UI 步骤条。

---

## 6. 与产品诉求的差距（为什么要改）

1. **Workflow 会变**：节点顺序不应写死为「永远 analysis → …」，例如 **音乐在用户上传/已生成时应作为更靠前的节点**；无音乐时再后移或由图决定。
2. **Music 节点缺失**：用户需要在进度条上看到 **Music**，且与真实流水线一致。
3. **单一真相来源**：仅靠前端扫 `event_type` 集合，在分支变多时会 **脆弱**（事件名冲突、顺序歧义、跳过某步时误判）。

---

## 7. 改造方案（建议，先协议后实现）

### 7.1 目标

- **后端 Runtime 或 router** 输出**可版本化**的 **本 run 的步骤路径 + 每步粗粒度状态**。
- **前端**根据该结构渲染 Sticky Todo；**不依赖**前端扫全量 `event_type` 来「猜」顺序（可作兜底）。

### 7.2 方案 A / B / C 对比（含「每会话 workflow 不同」与「少暴露信息」）

| 维度 | A — 仅 REST | B — 仅 SSE（如 `workflow_state`） | C — 混合 |
|------|-------------|-------------------------------------|----------|
| **每会话路径不同** | 支持（每次 GET 带回本会话 path） | **支持且更自然**：run 一开始或路径变更时推一条，后续状态更新再推 | 支持 |
| **实时性** | 依赖轮询或进页再拉 | **与现有生成流一致**，无需为进度条再拉 REST | 最好 |
| **刷新/重连** | 易丢「最后一次状态」除非再调 API | 需 **重连后补拉**（见下）或依赖消息持久化 | 重连用 A 补快照，平时用 B |
| **暴露面** | 多一个 HTTP 资源，可单独做权限/裁剪 | **可与现有 SSE 同通道**，payload 可控、可审计 | 两处都要维护 |
| **实现量** | 小 | 中（新 `MessageType` + 持久化策略） | 大 |

**为何更偏向 B（你的直觉合理）**

- 每个对话的 **path（节点顺序与是否出现某节点）** 可能不同；用 SSE **在 run 生命周期内推送「当前认定的 path + 状态」**，与「生成中」这件事绑定，心智统一。
- 前端已经在消费 SSE；进度条跟流走，**不必为 workflow 再开一个轮询或强依赖 REST**。

**B 的缺口（刷新/重连）**：若 `workflow_state` **与其它里程碑一样**走 **`async_send_event` + 写 DB**（见 **§7.10**），则会话详情/消息列表里**天然有最后一条**，**不必**再单独做 `GET .../workflow`——除非想减轻消息表体积再另议。

**少暴露信息（你关心的点）**

- 对外只约定：**`workflow_version` + 有序 `path[]`**，每项仅 **展示用 `id`、i18n `label_key`、粗 `state`、可选 `progress`**。
- **不要**放进 payload：内部执行节点名、prompt、工具参数、可反推业务的敏感字段。
- **`current_node_id` 不必下发**：前端用 **path 顺序 + 每步 `state`** 即可推导「进行到哪」——例如第一个 `running`，或第一个非 `completed`/`skipped`/`failed` 的节点；若全完成则全部打勾。**只定「path + 各步状态」就够用。**

### 7.3 字段释义（`id` / `label_key` / `state` / `progress`）

| 字段 | 含义 | 说明 |
|------|------|------|
| **`id`** | 步骤的稳定业务 id | 如 `music`、`analysis`、`storyboards`。用于前端逻辑与样式分支（**不是**内部图 uuid）。 |
| **`label_key`** | 文案键 | 如 `workflow.node.music`，由前端 i18n 映射成「音乐」；**避免**服务端直接下发长中文（除非产品要求）。 |
| **`state`** | 该步粗状态 | 建议枚举：`pending`（未开始）、`running`（进行中）、`completed`、`skipped`（本 run 不需要）、`failed`。 |
| **`progress`** | 可选 0–100 或 `{ completed, total }` | **仅**需要细粒度条的步骤（如分镜、镜头）；其它为 `null` 或不传。 |

**没有 `current_node_id`**：由前端根据 `path` 顺序与 `state` 推导高亮/转圈位置即可。

### 7.4 精简 payload 示例（偏 B，与 REST hydrate 同构）

```json
{
  "workflow_version": "2026.04",
  "run_id": "uuid",
  "path": [
    { "id": "music", "label_key": "workflow.node.music", "state": "completed", "progress": null },
    { "id": "analysis", "label_key": "workflow.node.analysis", "state": "running", "progress": null },
    { "id": "storyboards", "label_key": "workflow.node.storyboards", "state": "pending", "progress": { "completed": 3, "total": 12 } }
  ]
}
```

- **`path` 的顺序**即「大概的路径」；某 run 若没有音乐，可直接 **不出现** `music` 或出现为 `skipped`（产品二选一）。

### 7.5 后端职责划分

| 模块 | 职责 |
|------|------|
| **编排层**（Graph / pipeline） | 在 run 开始时根据**输入**（是否带曲、是否仅 MV、是否跳过分析）计算 **节点列表与顺序**。 |
| **状态机** | 每个节点：`pending` / `running` / `completed` / `skipped` / `failed`；可选 `progress`（分镜/镜头类）。 |
| **与现有事件关系** | 保留现有 `music_generated`、`video_analysis` 等用于业务与计费；**Workflow 状态**由编排层在适当时机更新，避免前端再「猜」。 |

### 7.6 Music 节点规则（产品需拍板）

- **已完成**：例如「用户上传音频并校验通过」或「本 run 已收到 `music_generated`」或「使用库内版权音乐 ID」——需产品枚举。
- **跳过**：无音乐需求时标记为 `skipped`，**不占「当前 active」** 或显示为灰色跳过。
- **顺序**：由 **`path` 数组顺序**表达；**禁止**仅靠前端写死「music 永远在第一位」。

### 7.7 前端改造要点（后续迭代）

1. **`MessageArea`**：见 **7.8 渐进式迁移**——**不必**一上来就删掉「扫 `event_type`」。
2. **`generation_todo`**：可继续作为「进度数字容器」，或逐步收缩为仅 **run 级 meta**（看是否仍需要兼容旧会话）。
3. **`completed_steps`**：在渐进方案下可 **长期保留** 作兜底；仅当全量改由服务端 `state` 驱动时再收缩。

### 7.8 渐进式迁移（推荐）：不是「全推翻」，也不是「只后端改、前端零改动」

**和现有逻辑的关系**

- 现有 **`hasAnyOrCompleted` / 全量消息 `event_type` 集合** 在「有哪些里程碑事件」这件事上 **仍然成立**，**不必**因为加了 `workflow_state` 就整段删掉。
- **方案 B** 更合理的落地是：**先用一个新事件补「本 run 的步骤顺序 + 是否包含某节点（如 music）」**；**完成与否** 可以继续用 **同一套 event → done 的映射**（你们已经维护了很久的那套），只在映射里 **给 music 等补上对应 `event_type`** 即可。

**两档实现（由浅入深）**

| 档位 | 后端多做什么 | 前端多做什么 |
|------|----------------|----------------|
| **A — 最小** | SSE 带 `path: [{ id }]`（顺序 + 出现哪些节点） | 用 `path` **生成步骤条顺序与列**；每步 **done/active** 仍用 **现有 event 推断**（加 music 映射） |
| **B — 完整** | 再带每步 `state`（可选） | 可逐步用服务端 `state` 覆盖「进行中/跳过」，事件推断作 **fallback** |

**不是「全改」**：除非你明确要 **单一真相 = 服务端 state**，否则可以 **长期混合**——**path 来自 SSE，done 来自事件**。

**「后端改完前端就能直接展示、不用 i18n」？**

- **做不到完全零前端**：多语言产品 **要么** 前端用 `label_key` 做 i18n，**要么** 后端按 `Accept-Language` / 用户语言下发 **已翻译的 `label` 字符串**（后端要维护多语言或翻译服务）。
- **折中**：第一版 **`path` 只带 `id`**（如 `music`），前端 **固定写死** `id → 文案键` 的表（改文案仍发版）；或 **`label_key` + 前端 i18n**（推荐，和现有 Cuti 一致）。

### 7.9 版本与兼容

- `workflow_version` + `path[].id` 稳定化；文案用 **`label_key` + 前端 i18n** 或后端按语言下发 `label`（二选一）。
- 旧会话无 `workflow_state`：继续走 **legacy 固定 7 步 + 现有 event 推断**。

### 7.10 `path` 怎么落库：新增 `MessageType` + `send_event` + DB（不必单独 workflow API）

可以、也推荐与现有里程碑一致：

1. 在 **`MessageType`** 中新增一项，例如 **`WORKFLOW_STATE`**（值字符串如 `workflow_state`）。
2. 通过 **`async_send_event(MessageType.WORKFLOW_STATE, extra_data={ workflow_version, run_id, path, ... })`** 推送 SSE，并 **与其它 `GENERATED_EVENTS` 一样持久化到会话消息**（是否 `hidden`、是否在 UI 出气泡由产品定；**底部条只读 `event_data`** 即可）。
3. 前端渲染：在 **messages** 里取 **当前 run 下最后一条** `event_type === "workflow_state"`，解析 **`path`**；刷新/重连 **拉会话详情** 即可恢复，**无需**单独 `GET /workflow`。

这样 **不增加**「第二套 workflow 专用接口」，和 **`music_generated`、`video_analysis`** 同一套心智。

---

## 8. 小结（直接回答用户原问）

| 问题 | 答案 |
|------|------|
| 后端会传 `generation_todo` 吗？ | **不会**（非 `MessageType`）。 |
| 是虚拟的吗？ | **是前端合成消息**，用于 UI 聚合。 |
| 谁插入？ | **前端**（`CreateVideoPage` 内多种分支）。 |
| VideoAgent 还是 VideoChatAgent？ | **两者都不发该类型**；与谁的业务无关。 |
| `completed_steps` 后端带吗？ | **当前不带**；主要由 **`rebuildGenerationTodo` 从消息推断**；运行时展示更多依赖 **全消息 `event_type` 集合**。 |
| Music 有节点吗？ | **当前底部 7 步没有 Music**；`music_generated` 未映射到任一步。 |

---

## 9. 待决策清单（实施前）

- [ ] **`MessageType.WORKFLOW_STATE`** 命名与是否与其它里程碑一样 **持久化**。
- [ ] Music：**path 是否含 `music`** 与 **`_noMusic`（真无配乐）** 的判定（与 **DB / Music section** 对齐）。
- [ ] `workflow_state` 消息是否 **hidden**、是否出气泡。
- [ ] 旧会话兼容策略与灰度方式。

---

## 10. 仅加动态 `path`、其余仍用旧推断 — Music 专项分析（**Music section / DB 为准**）

> 约定：**不改**「用会话消息里的 `event_type` + 现有数据推断」的总体思路；**只加** `workflow_state.path` 决定**有哪些步、顺序**。  
> **产品真值**：视频「音乐」= **右侧 Music 区块** + **DB 有对应数据**（如 `music_generations`）。**有无歌词**、**AI 生成或用户上传**，只要 **section 有数据、用户能看见**，即算「音乐阶段已有结果」。**不是**单独指 Suno 单独生成。  
> **真正无配乐**：**`_noMusic`**（或业务等价）——与「section 有数据」对立。

### 10.1 多种信号：事件 vs DB

| 信号 | 含义 |
|------|------|
| **DB：`music_generations` 等有记录** | **Music section 可展示**的根基；生成 / 上传落库均可 |
| **`music_generated`** | 管线里程碑，常与落库同事务或紧邻 |
| **`music_generation_progress`** | 仅进度 |
| **`music_agent_generated`** | 音乐独立 Agent；**不是**视频 Music section 定义本身 |

### 10.2 「有音乐」vs「无配乐」

| 情况 | 说明 |
|------|------|
| **有音乐** | DB 有数据 → section 可展示 → 音乐阶段已就绪。 |
| **无配乐** | **`_noMusic`**（真无）→ **`path` 不应含 `music`**（或标 `skipped`，PM 定）。 |

### 10.3 前端 music 步 `done`（与右侧对齐）

- **消息**：`hasAnyOrCompleted(["music_generated"])`；
- **数据**：`musicData?.music_generations?.length` 等 → 与 `LazyVideoResultsPanel` materialize 逻辑一致。

**以 DB + section 为准**时，落库后须有 **事件或可轮询数据**，底部与右侧一致。

### 10.4 右侧面板 vs 底部：顺序

- **`path`** 由后端定序；第一版不必强行统一两侧旧顺序。

### 10.5 后端：写 DB 与吐事件

- 生成或上传，在 **section 可展示** 时落库；**`music_generated`** 在音乐阶段完成时发送（含上传落库完成场景需统一约定）。

### 10.6 `path` 里何时带 `music`

- 非 **`_noMusic` 无配乐**、且要展示音乐步 → **含 `music`**。
- **真无配乐** → **不含** `music`。

---

## 11. 有哪几种情况？`path` 怎么回、在哪回？

### 11.1 典型情况（可与 PM 收敛）

| 情况 | `path` 里是否含 `music` | 顺序意图（示例） |
|------|-------------------------|------------------|
| A — 需要 **AI 生成 BGM**，且要在进度条占位 | **含** `music` | 如 `music` 在 `analysis` 前或后，由编排定 |
| B — **用户已上传** 用曲，本 run **不生成** BGM | **可不含** `music`；或含且标 `skipped`/`completed`（产品定） | 无格或显示跳过 |
| C — **无配乐**（纯对话 / `_noMusic`） | **不含** `music` | 底部不出现音乐格 |
| D — 音乐在流水线 **偏后**（先分析再作曲） | **含** `music`，顺序在 `story_style` 之后等 | 仅由 `path` 数组顺序表达 |
| E — **重连 / 刷新** | 与当时 run 一致 | 见 11.3 hydrate |

**缺的 id = 不展示该步**；顺序 = `path` 数组顺序。

### 11.2 `path` 怎么「返回」——载体

- **推荐**：新增 **`MessageType.WORKFLOW_STATE`（值如 `workflow_state`）**，**`async_send_event` + 与其它里程碑一样写 DB**（见 **§7.10**）。payload：`workflow_version`、`run_id`、`path`。
- **实时**：走现有 SSE；**刷新/重连**：拉 **会话消息列表** 即含最后一条 `workflow_state`，**不必**单独 `GET .../workflow`（除非团队想减负另议）。

前端：按 **`run_id` 取最后一条** `workflow_state` 的 `path`；**每步 done** 仍用 **§10**（事件 + `musicData` 等与右侧一致）。

### 11.3 「在哪返回」——建议后端落点

| 落点 | 做什么 |
|------|--------|
| **① Run 可启动时**（用户确认 / 收到 `user_input` 后、进 graph 前） | 根据本 run 输入 **算初始 `path`**，**发第一条 `workflow_state`** |
| **② 编排中途变更（可选）** | 再推 **更新后的全量 `path`**（首版全量替换最简单） |
| **③ 持久化** | 与其它事件一致 **写会话消息**（见 §7.10），刷新即恢复 |

**集中一处**（如 `build_workflow_path(run_context)`），**不要**每个子 service 各写一段 path。

### 11.4 VideoAgent / VideoChatAgent

共用 **`async_send_event`** 时，在 **路由 / pipeline 入口**（如 `agent_router_service` 在进 graph 前）发 **`workflow_state`**，可 **一处实现、两处复用**。

### 11.5 最小落地顺序

1. **`MessageType.WORKFLOW_STATE`** + `async_send_event` + DB。  
2. 前端从 **messages** 读 `path`；**music done** 与 **Music section / DB** 对齐（§10）。  
3. 刷新：会话详情自带消息，**无需**单独 workflow 接口。
