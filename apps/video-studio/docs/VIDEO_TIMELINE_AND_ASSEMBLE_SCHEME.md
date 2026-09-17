# 视频时间线、合成（Assemble）与再生成：关系说明与 A 方法方案

本文基于当前代码库（`cuti-front-end-lovable`、`Cuti-VideoAgent`）整理：**流程内自动 assemble**、**用户主动 assemble**、**regenerate** 的差异；**shot / segment / 音乐** 的对应关系与一对多；以及「**不等到全部完成再在对应时间点展示**」时**前端与协议上需要什么**；并与前文 **A 方法**（单条 FFmpeg/assemble 成片、独立时间线编辑态）合并为一页方案。

---

## 1. 两种「最终成片」的入口

| 方式 | 触发者 | 代码/路径 | 说明 |
|------|--------|------------|------|
| **流程内自动** | Runtime 到达汇聚步骤 | `video_assembly` 步骤 → `execute_video_merge_core` | 不经过 HTTP 的 `video-assembly`；在 **同一 thread、同一 state** 上从 DB 拉全量资源。 |
| **用户主动** | 前端/管理端调 API | `POST /agent-router/video-editing/video-assembly` | `VideoAssemblyRequest`：`thread_id` 必填；`videos`（按 shot 选版 + 可先 **sync**）；`segment_versions`（按 segment 选版，偏 audio-driven）。 |

**注意**

- 两者最终都进 **`execute_video_merge_core` / `execute_assembly_strategy`**，但**入参来源不同**（图内 state vs `video_assembly_by_request` 从 DB 重算 `VideoAssemblyData`）。
- **必传 `thread_id`（不是 `run_id`）**；`VideoSegmentsSection` 若发 `run_id` 需改为与 Pydantic 一致，并带 `Authorization`（与 `LazyShotsSection` 一致）。

### 1.1 图内工作流与 assemble 的位置（`video_agent_service._build_graph`）

- 主线：… → `video_generation` → `gate_after_shots` → `video_segments` → 与 `narration_generation`、`music_bgm_generation` **三边汇聚** → **`video_assembly`** → `END`。
- **旁白、分段视频（segments 节点）、BGM** 在合成前**并行**；只有都完成后才进 `video_assembly`（`music_bgm_generation` 在门控/assembly 前另有 **task await** 兜底，避免 BGM 未落库就合成）。

### 1.2 用户点「更新视频/合成」时

- `LazyShotsSection` 发 **`thread_id` + `segment_versions: []` + 可选 `videos` + `user_option`**，与 `VideoAssemblyRequest` 一致。
- `videos` 非空时，服务端**先** `sync_segments_by_request`（`force=True`）再合，保证 shot 上选中版本与 segment/DB 一致。

### 1.3 与「A 方法」的衔接

- 单一成片引擎：**都是** 现有 `VideoAssemblyData` + `execute_video_merge_core`（及 MSC/FFmpeg 调用）。
- 未来在「编辑时间线」后导出：仍**只**扩 `VideoAssemblyRequest` 与 merge 前处理（如 trim），**不**在首版引入第二套出片（如 Remotion `renderMedia` 替代 assemble）。

---

## 2. Regenerate（再生成）与流程内生成的区别

| 维度 | 主流程 | Regenerate（关键帧/镜头） |
|------|--------|---------------------------|
| 入口 | Runtime 步骤内排队生成 | `task_enqueue_service.execute_regenerate_keyframes` / `execute_regenerate_videos` 等，新建 **`conversation_run`**，类型为 REGENERATE_* |
| 写库 | 正常 workflow 写版本 | **追加新版本**；产品约定：**不自动**把新结果设为 current（可依赖 `select_version`） |
| 结束动作 | 继续走图、直到 `video_assembly` | **不自动**接一段「再 assemble」；需用户/助手再调 **显式** `video-assembly` 或等下一轮全片流程。 |
| 与终片关系 | 自然产出 `video_assembly` 与 `VideoAssembly` 记录 | 只更新某 shot 的**素材版本**；**终片**要么旧、要么再点一次合成/更新视频。 |

**已文档化的注意**（`video_edit/system_prompt.py` 等）

- 关键帧出新版后，若**未** `select_version` 为当前选用，**后续** `regenerate_videos` 可能仍吃**旧关键帧**——助手侧须引导选用。
- 对用户不要声称「已按新画面出片」若**选用/合成**未跟上。

---

## 3. Shot、Segment、音乐：关系与「一对多」

### 3.1 Shot 层（`video_generations`）

- **一镜一行**（`shot_number`），多 **版本** = `video_generation_versions`（regenerate 产生多条）。
- 一镜**通常**挂关键帧（`keyframe_id` 或 `keyframe_ids`），与分镜/场景/旁白有 DB 级关联。

### 3.2 Segment 层（`video_segments` + `video_segment_versions`）——**音频/整轨驱动** 路径

- **一个 `VideoSegment`** = 逻辑上的「**一段**」与「**一个 segment_number**」，带有：
  - `video_generation_ids: List` —— **可多个 shot** 落在**同一**音频/音乐分片下（`audio_segment_id` 在映射里把多镜绑到同一段上）。
  - `music_generation_id` —— **本段**若对应**一段** music 行，**多数模型下每 segment 对一条**（可空，视业务）。
- **Segment 版本** `video_segment_versions`：合并结果视频 URL、关联各 `video_generation_version_ids` 等，支持多版本/重试。

**一对多**

- **1 个 segment : N 个 video_generations** —— 当**同一** `audio_segment` 上排了**多个 shot** 的视频（见 `video_segments_service._process_single_segment` 里用 `audio_segment_id` 收集 `video_generation_ids`）。
- **1 个 video_generation** —— 在 shot 维度的「一镜一主行」；**多版** 在 `video_generation_versions`。
- **1 个 shot** —— **0..* 与 segment 的交叠**（多镜可并进同一 segment 的合成结果，取决于**音频分片**如何切）。

### 3.3 音乐与两种组装模式

- `VideoAssemblyData.assembly_mode`（`video_state.VideoAssemblyData`）：
  - `audio_driven`：有 **audio_transcription** 等，按**整轨/分片**驱动片段与 BGM/分段音乐。
  - `narration_driven`：有旁白/音效等，按旁白+镜头常规拼接；可加 BGM。
  - `video_driven`：偏仅拼镜头、少轨。
- **Music 在 DB 里**常按 `conversation_id` + `thread_id` 拉，**`music_data` 的 key 多为 `audio_segment_id`**，与 segment/shot 的绑定在 `get_music_data_for_videos` 与 `video_assembly_data` 构建中体现。  
- **全片 BGM** 另有 `music_bgm_generation` 与图里 **await 兜底**逻辑，避免合成时 BGM 未就绪。

**注意**

- 「音乐片段」与「视频 segment」在名字上都叫 segment 时，要在文档与 UI 上**区分**「**音频分片 id**（`audio_segment_id`）」与「**业务 VideoSegment 行**（`video_segments` 表）」避免沟通歧义。

---

## 4. 你关心的两件事：未全部完成，能否在「对应点」出现？

### 4.1 关键帧

- **现状**：`LazyShotsSection` / 分镜区能按 `shot_number` 铺**固定槽位**；无版本时 `versions: []` 可显示占位；`keyframes` 的 API/轮询（如 `keyframeTodoFallbackFromApi` in `MessageArea`）用 **有 `keyframe_url` 的条数**算进度。
- **「生成 1 个就显示首帧」在逻辑上**可行，条件：
  1. **能拿到** 该镜某一关键帧版本（或内层事件）的 **可展示 URL**（一落地就刷列表/WS/poll）。
  2. 槽位按 **`shot_number` 或** 将来时间线给定的 **时间槽** 排序即可，**不必**等**所有**关键帧完成。

### 4.2 视频

- **未全部转码完**：只要某 `video_generation_version` 有 **可播 URL**（或 HLS/渐进 MP4），即可在**该镜槽**放 `<VideoWithCleanup />`，与「全部 shot 都 success」解耦；已有 **progress** 事件/字段（`video_generation_progress` 等）支撑进度条。
- **更贴近「时间轴上某一秒」的展示**（而不仅是**第 N 个卡片**）需要**额外**：
  - 每个槽位/clip 的 **在主轴上的起止时间**（来自**故事板/语音分段时长/拍长估算**）；
  - 一条**主轴 UI**（横向时间尺 + 绝对/相对 `left/width`），**不等**后段跑完，前段已有 URL 就可渲染。

**结论（产品语义）**  
- **是**：不必等**整条任务全完成**才在「对应**顺序位置**（第 N 镜）」展示**首帧或部分可用视频**——与当前「槽位+轮询」**一致**。  
- **要「**时刻**在物理时间**轴**上的对位」**（像剪映轨）：除 URL 与状态外，还需 **每段** `t_start/t_end`（或**累计 offset**）与 **一条时间线布局**；这是 A 方法里**编辑/预览**层要补的数据模型，而非只靠 shot 下标。

---

## 5. 要做到「可渐进 + 可时间对位 + 可编辑」需要的能力清单

| 能力 | 前端 | 后端/数据 |
|------|------|------------|
| 关键帧/视频一就绪就显 | 槽位+轮询或 WS+按 shot 更新；已有 `LazyShots` 类模式 | 版本/URL 尽快可 GET；**无需**为「显示」多一条 assemble。 |
| 全片进度/终片 | `getVideoAssemblyData` / 事件里 `video_assembly_uuid` | 流程内或手动 **assemble** 后写 `video_assembly`。 |
| 时间线占位（**物理时间**） | **新增**：主轴组件 + 每段 `startMs/durationMs` 或 `endMs` | 从**分镜+旁白+音频分段**可推导或从 DB 加字段；**可与 assemble 用同一**「计划时长」**避免预览与导出漂移（计划阶段明确策略）。 |
| 编辑后导出 | **EditState** 序列化 → 现有 `video-assembly` body，逐步加 trim 等 | **扩展** `VideoAssemblyRequest` + `execute_video_merge_core` 前 **trim/混音**（MSC 已具备 trim 等能力时可接）。 |
| Regenerate 与终片 | 显式说明「只出新版本，不自动替换终片」；按钮「更新视频」= 再 `video-assembly` | 与现有一致。 |

---

## 6. 工程注意（与 assemble / regenerate 的交叉点）

1. **选用版本**：新 regenerate 的默认行为是**增加版本**；**assemble** 取的是**当前 request 中选的版** 或 **current_version_index**；两者不一致时，用户会困惑——需在 UI/助手侧显式。  
2. **sync 再合**：`videos[ ].selected_version` 路径会 **sync segment**，若用户**只**改 keyframe/视频不点合成，**DB** 与**右侧面板**可能短暂不一致。  
3. **BGM/旁白/分段**：`video_assembly` 汇聚**旁白+segments+BGM 任务**；**手动** assemble 时同样从 `thread` 拉**当前**资源，注意 **BGM 未就绪** 时的失败日志与重试。  
4. **一对多 shot→segment**：展示「某段合并视频」时，**segment 版本**与 **多个 shot 版本** 的**选用**要统一（sync 的意义即在此）。  

---

## 7. 与代码核对后的重要细节（易忽略）

### 7.1 `CreateVideoPage` 分阶段数据轮询（`pollOnce`）

- 文件：`cuti-front-end-lovable/src/components/CreateVideoPage.tsx`（约 877–1052 行）。
- **gating 链**：`characters` → `scenes` → `keyframes`（须 `hasScenesContent`）→ `video_generations`（须 `hasKeyframesContent`）→ `getVideoAssemblyData`（须 `hasVideosContent` 且 `effectiveAssemblyUuid`）等。
- **与「渐进出现」相冲突处**（实现细节）  
  - 把结果写入 `keyframesData` 的条件为 `res.code === 0 && res.data?.keyframes?.length`：**`keyframes` 仍为空列表**时，不会把接口里的 `shot_total` 等元数据写进 state。  
  - 把结果写入 `videosData` 的条件为 `res.code === 0 && res.data?.video_generations?.length`：而后端在**尚无任何** `video_generations` 行时，仍会返回 `"video_generations": []` 与 **`"total": expected_shot_total_vg`**（见 7.2）。前端**丢弃**该响应，导致 `LazyShotsSection` 依赖的 **`videosData.total` 的占位**往往要等到**首条**视频行落库后才会出现。  
- **建议改动（仅前端，小步）**：在 `code === 0` 时，**即使** `keyframes.length === 0` 或 `video_generations.length === 0` 也执行 `updateChatDataState`（可 merge，避免覆盖成 undefined），**至少**保留 `shot_total`、`total` 与空数组，供 **Todo/占位/分母** 与「N 个空槽」用。注意与 `stageDataPollKeyRef` 的联动，避免死循环（合并策略与现有 `ref` 一致即可）。

### 7.2 后端 `GET` 形态的按 thread 聚合

- 关键帧与镜头列表在路由上为 **POST** body 里带 `thread_id`（见下），实现文件：`Cuti-VideoAgent/storybook_app/api/agent/video_analysis_endpoints.py`。
  - `post /keyframes-by-thread`：`get_keyframes_data_by_thread` — 无行时可返回 `keyframes: []` 与计算后的 `shot_total` / `total`。
  - `post /video-generations-by-thread`：`get_video_generations_data_by_thread` — 无行时返回 `video_generations: []` 与 **`total: expected_shot_total_vg`**（从 `detailed_shots` 数来）。

### 7.3 `VideoSegmentsSection` 与 Pydantic 入参

- 文件：`cuti-front-end-lovable/src/components/video/VideoSegmentsSection.tsx`  
- 若请求体仍为 `run_id` 而缺 **`thread_id`**，与 `VideoAssemblyRequest`（`agent_router_endpoints.py`）不一致，**需改为** 与 `LazyShotsSection` 相同：`| thread_id` + `segment_versions` + **`Authorization: Bearer`_|。

---

## 8. 可落地的改造框架（分阶段 + 要改什么代码）

以下为 **A 方法** 与**渐进/时间线**的**实现地图**，按优先级拆 PR。

### 阶段 0：数据可见性与 API 一致（小改动、高收益）

| 目标 | 位置 | 改什么 |
|------|------|--------|
| 轮询在「空列表」时仍落库 `shot_total` / `total` | `CreateVideoPage.tsx` 内 `getKeyframesDataByThreadId` / `getVideoGenerationsDataByThreadId` 的 `then` | 条件由「仅当 length>0」改为 **`code===0` 即更新**（或 merge 元数据 + 空数组），见 7.1。 |
| 合成 body 与后端一致 | `VideoSegmentsSection.tsx` | `thread_id`（= props `threadId`）+ `segment_versions`；`Authorization`；**勿**以 `run_id` 替代 `thread_id`。 |
| 轻量类型 | `src/types/api.ts` 或新 `src/types/stageData.ts` | 为 by-thread 响应补充 `shot_total?`、`total?` 的 TS 结构，减 `any`。 |

**验收**：`detailed_shots` 已有、但 DB 尚无关键帧/尚无视频行时，UI 能拿到 **镜数分母**；`LazyShotsSection` 的 `displayVideos` 在 `total>0` 时可**更早**出现横滑槽位。

---

### 阶段 1：单出口构造「组片」请求（仍不扩后端）

| 目标 | 位置 | 改什么 |
|------|------|--------|
| 可测、可复用的 request builder | 新建如 `src/lib/buildVideoAssemblyRequest.ts` | 入参：`threadId`、`source: 'shots' | 'segments'`、选中的 `version` 映射、可选 `userOption`；**输出** 与现 `LazyShotsSection` 的 `body` 一致（`thread_id` + `videos`? + `segment_versions`?）。 |
| 去重 | `LazyShotsSection.tsx`、`ShotsSection.tsx`、**修正后的** `VideoSegmentsSection.tsx` | 调 builder + 统一 `fetch`/`makeRequest`（可抽 `src/services/cutiVideoAssembly.ts` 一个 `postVideoAssembly()`）。 |
| 管理端 | `api.ts` `adminVideoAssembly` | 可复用 builder 或显式注「admin 专用参数」。 |

---

### 阶段 2：EditProject 编辑态（A 的壳，出片仍一条 assemble）

| 目标 | 位置 | 改什么 |
|------|------|--------|
| 类型 | `src/types/videoEditProject.ts` | 如 `threadId`、`clips: { ref: shot \| segment, versionId, trim? }[]`；v1 可**不做**重排，仅做选版+预留 trim 字段。 |
| Hook | `src/hooks/useVideoEditProject.ts` | 从 `videosData`/segment 列表**初始化**；`commit` → `buildVideoAssemblyRequest` → HTTP。 |
| UI | 成片区 `src/components/video/FinalVideoTimelinePanel.tsx`（在 `VideoAssemblySection` 播放器下方，不与镜头区混用） | 可点击分镜块或轨道 seek，与成片 `<video>` 同一播放状态。 |

**本阶段后端可不动。**

---

### 阶段 3：物理时间轴仅预览（与成片精确对齐在阶段 4+）

| 目标 | 位置 | 改什么 |
|------|------|--------|
| 每镜时间 | `useVideoEditProject` 或 selector | `duration`：优先用 `get_video_generations_data_by_thread` 已下放的 **version/shot 的 `duration`**；无则用 `detailed_shot.duration`；再不行再占位常量并注「仅预览」。
| 组件 | `src/components/video/TimelineTrack.tsx` | 横条 + `left/width%` 或 `transform`；**不**直写进 `VideoAssembly`。
| 音频对位（可选） | 已有 `getAudioTranscription`（`api.ts`）+ `types/api` 的 `sections` / `AudioSegment` | 若与 **audio_driven** 同轨展示，**仅读**不改编码链。

---

### 阶段 4：每段 trim 进 `execute` 前（**VideoAgent + Media**）

| 目标 | 位置 | 改什么 |
|------|------|--------|
| 协议 | `agent_router_endpoints.py` `VideoAssemblyRequest` | 可选如 `clip_trims: [...]`（字段名实现前可再对表）。  
| 服务 | `video_agent_service.py` `video_assembly_by_request` | 在组好 `VideoAssemblyData` 之后、调 `execute_video_merge_core` **前**，对对应 **source** `video_url` 调 **Cuti-Media-Service** 已有 `trim`（`Cuti-Media-Service/.../ffmpeg_service.py` `trim_video` 等）。  
| 合成 | `video_assembly_service.py` | 可抽 `apply_trims(assembly_data, trims)` 保持单入口。  
| 前端 | `buildVideoAssemblyRequest` + `useVideoEditProject` | 把 `trim` 从编辑态带上来。  

---

### 阶段 5：Regenerate 与终片（文案/提示）

| 目标 | 位置 | 改什么 |
|------|------|--------|
| 新版权未自动进终片 | `i18n/translations.ts` + `LazyShotsSection` 成功区 | 短句提示「点更新视频/合成以更新终片」（按需）。  
| 选用提示 | 若有「未选中新版」检测（对比 `version_number` 与 `current_version_index`）| Badge 或 Tooltip（依赖现有 props，非必选）。  

---

## 9. 仓库职责（实现分工）

| 仓库 | 本方案中的职责 |
|------|----------------|
| `cuti-front-end-lovable` | 轮询与阶段 0 占位、Results 区与 `LazyShotsSection`、**builder** 与**时间线** UI、调 `.../agent-router/.../video-assembly` 与 `.../video-analysis/...-by-thread`。  
| `Cuti-VideoAgent` | 图内 assemble、HTTP `VideoAssemblyRequest`、**阶段 4** 的 merge 前 trim 与对 MSC 的调用。  
| `Cuti-Media-Service` | `trim`/`concat` 等，被上者 HTTP 内调。  
| `Cuti-VideoChatAgent` | 不阻塞成片链；**仅**若要在对话里**选版/regenerate 编排**时再与上面对齐。  

---

## 10. 参考路径速查

- 图与节点：`Cuti-VideoAgent/storybook_app/services/agent/video_agent_service.py`（`_build_graph`）  
- 合成核：`Cuti-VideoAgent/storybook_app/services/agent/video/video_assembly_service.py`  
- 请求体：`Cuti-VideoAgent/storybook_app/api/agent/agent_router_endpoints.py` — `VideoAssemblyRequest`  
- 按 thread 列表：`.../video_analysis_endpoints.py` — `keyframes-by-thread`、`video-generations-by-thread`  
- 前端主路径：`CreateVideoPage.tsx`（轮询与 `updateChatDataState`）、`LazyShotsSection.tsx`（`thread_id` + `videos` 组片）  

**Remotion** 不列入必改；若使用，**仅**放在阶段 2/3 的**预览**层，成片仍走 `video-assembly` + FFmpeg/MSC 链。  

---

## 11. Shot、Keyframe、Video、Segment、Music 关系再核对（DB vs 实际代码）

**主文档（表级 M:N 与全链路）**以仓库内为准：  
`Cuti-VideoAgent/docs/artifact-relationships.md`（产物树、`audio_segment_ids` 传播、BGM vs per-segment、**第五节** 对 `system_prompt`/get_artifact_detail 的缺口说明）。

本节只回答两件事：**(A) 在「业务路径」上更像几对几；(B) 哪些为了可控复杂度假设成「用第一个 ID」**，以免把完整 M:N 全实现进热路径。

### 11.1 镜头脚本层（`video_detailed_shots` / shot_number）

- **1 : 1（概念上强约束）**：一镜一 **DetailedShot**、一 **shot_number** 贯穿：分镜、关键帧行、**video_generations 一行/镜** 均按此编号对齐。不是「多镜共享一条 detailed_shot」。

### 11.2 Keyframe ↔ Shot

- **DB**：`video_keyframes` 按行挂**shot 语义**；一个镜头可对应**多条** `video_keyframe` 记录（如首/尾、多版本在 **versions** 表）。
- **对 Video**：`VideoGenerationDB` 同时有 `keyframe_id`（**向后兼容、单主关键帧**）和 `keyframe_ids`（**新：首+尾 等多帧 ID 列表**）。见 `storybook_app/schemas/video/video_generation.py` 注释。
- **实践**：UI「按镜」的 Storyboards ≈ **一镜一关键帧主行 + 多 `KeyframeVersion`**，尾帧等走 `keyframe_ids` / `keyframe_version_ids` 不强行做成「多对多可任意指」的通用图；**和 artifact 文档的 M:N 不矛盾**，是产品上的**一主多辅**实现。

### 11.3 Video（`video_generations` / versions）↔ Keyframe

- **N(版本) : 1(主行)** 每行 `video_generations` = **一镜的生成槽**；**regenerate** 只加 **video_generation_versions**，不新开镜行。
- **一版视频**可引用**多个**关键帧版本：`keyframe_version_ids: List`（同 schema）。  
→ **一镜 一 video_generation 行 : 0..* keyframe 版本**（常见 1~2 个，首+尾），不是「一镜多行 video」。

### 11.4 Video（shot）↔ 音频 `video_audio_segment`（**代码里显式简化为「主 segment」**）

- **DB/artifact** 上可为 **M:N**（`audio_segment_ids: List` 在 shot / keyframe / music 多表传播）。
- **热路径**里多处**只为归组/裁切**取**第一个**：
  - `video_generation_service._build_lipsync_audio_url_map`：按 `shot.audio_segment_ids[0]` 把**同一**转录 `audio_segment` 下多镜分组；`music` URL 也常用 `latest.audio_segment_ids[0]`（同文件 1399、1423–1424 行附近）。
- **含义**：若一镜的 `audio_segment_ids` 有多元素，**当前** lipsync/时长诊断逻辑**不**逐元素展开，**以 [0] 为桶**——这是**实现级简化**，不是全表 M:N 跑满。

### 11.5 `video_segments`（业务「合并段」）↔ `video_generations`（**一对多，常见**）

- 见 `video_segments_service._process_single_segment`：同一 **audio_segment 维度**下可收集**多个** `video_generation_id` 写进**一条** `VideoSegment` 的 `video_generation_ids[]`。
- **1 个 VideoSegment 行 : N 个 video_generation 行** 在 **audio-driven/按段合并** 时存在；`segment_number` 是段序，**不等于** `shot_number` 一一对应。
- **1 个 video_generation 行** 在 narration/video-driven 的叙述里，往往先被**单独 concat**；**进入** `video_segment` 是**另一条**后处理路径（audio 驱动合并）。  
→ 对外 Explain：**镜（shot）= 主编辑单位；段（segment）= 与**音乐/整轨时间**对齐的合并层**，二者勿混。

### 11.6 Music（`video_music_generations`）↔ segment / 成片

- **Per-segment 裁剪**：**多行** `video_music_generations`（**每** `audio_segment`/策略一行），`video_music_generation_versions.audio_segment_ids` 指向切来的音。
- **BGM 全曲**：**常一行** `is_full_story_music=True`，**不**再按 `audio_segment` 多行，走 **叠加到成片** 的路径（`artifact-relationships` 中 `add_background_music_to_video` 与 per-segment concat 的区分）。
- **VideoSegment.music_generation_id**：**N:1**，一段合并结果**主挂**一个 music 行（**辅** 靠版本表 `music_generation_version_id` 等），不是「多首拼成一个 segment 主行」的通用 M:N 模型。

### 11.7 和「你记得简化过不是多对多」的对应

- 表**仍**可表达 M:N（`JSON` 列表字段）；**执行策略**在多处 **以第一个 segment、以 shot 为桶、以「一镜一 video 行」** 降低组合爆炸。
- 若产品要**严格**「一镜多 audio_segment 各自一条音乐轨」，**不能**只依赖现 `[0]` 分桶，需**改** `_build_lipsync_audio_url_map` 及同类的「取首 ID」逻辑，并过一遍 assembly。

### 11.8 对当前 `VIDEO_TIMELINE` 方案与代码的影响

| 点 | 是否需要为「关系」本身改代码 |
|----|------------------------------|
| 前端的 **一镜一卡**（`LazyShotsSection` 按 `shot_number`） | **不必须**；与 `video_generations` 一镜一行的习惯一致。 |
| **时间轴**按「**物理时间**」铺轨 | 若**严格**与 audio-driven 一致，应**优先**从**转录 segment 边界 + shot.duration** 或**后端**已有字段推导，并**知悉** 代码里用 `[0]` 时**极端多 segment** 的镜**可能与内心预期不完全一致**；属**产品/精度**再迭代。 |
| `get_artifact_detail` 缺 segment 链、prompt 说明不足 | 见 `artifact-relationships.md` 第五节、第六节；**偏 LLM/调试**，不阻塞时间线/轮询 **阶段 0**；若要 companion **准确** 讲「从 video 到 segment 再到 assembly」再补。 |
| **无** 因为「关系是 1:1 还是 M:N」而必须**立刻**改的 **VideoAssembly** 或 **Vite** 层逻辑 | 除非你在 UI **错误假定了**「segment_number 恒等于 shot_number」——有 audio 合并时**不成立**，segment UI 要按 **segment API** 展示。 |

**结论**：以 **`artifact-relationships.md` 为真值表**；**实现**在 `audio_segment_ids[0]`、一镜一 `video_generation` 行等处做了**有意的简化**。时间线与 assemble 的近期改造（本文件 §7–8）**不必**先为「完整 M:N」重做数据模型，但若要做**帧级/多 segment 一镜**的**精确**对齐，要**点名列出**要改的函数（上表 11.4、11.7）而非只改 DB。

---

*本文件为架构与实现指导用，若接口字段变更请以 OpenAPI/代码为准。*
