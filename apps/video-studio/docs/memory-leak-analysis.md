# 前端内存泄漏分析（Detached 节点与事件监听）

根据 Memory Profile 结论：大量 Detached `<video>`、Detached Window 占 44% Retained Size、以及 1 万+ 游离事件监听器，可能导致 Chrome/夸克卡死或黑屏。以下为代码侧可能原因与修复点。

---

## 1. 幽灵视频节点 (Detached `<video>`)

### 1.1 ShotsCheckPage — 缩略图用 createElement('video')（最可能对应 164 个）

**位置**: `src/components/video-check/ShotsCheckPage.tsx`  
**逻辑**: `useEffect` 内对每个 shot 执行 `document.createElement('video')`，设置 `src`、`addEventListener`、`video.load()`，用于抽取首帧缩略图。这些 video 从未挂到 DOM。

**问题**:
- 没有 effect cleanup：组件卸载或 `shots`/`videoThumbnails` 变化时，已创建的 video 未做任何释放。
- 每次 effect 重跑都会为每个 shot 再创建新 video，旧 video 既未移除监听器也未清空 `src`，一直留在内存，形成 Detached。
- 会话中有几十个 shot 且用户多次进入/离开该页或切换 grid/gallery 时，很容易累积到上百个 Detached video。

**修复**: 在 effect 的 return 中统一清理：对本次 effect 创建的所有 video 执行 `removeEventListener`、`video.src = ""`、`video.load()`；用 ref 记录当前批次的 video 引用以便 cleanup 时释放。

---

### 1.2 VideoCheckCanvasPage — 取 metadata 的 createElement('video')

**位置**: `src/components/video-check/VideoCheckCanvasPage.tsx`  
**逻辑**: `useEffect` 里 `document.createElement('video')`，设 `src = finalVideoUrl`，只用于 `loadedmetadata` 取宽高。

**问题**: cleanup 只做了 `removeEventListener`，没有 `video.src = ""` 和 `video.load()`，解码缓冲和元素本身会一直占用内存。

**修复**: 在 effect cleanup 中增加 `video.src = ""`、`video.load()`。

---

### 1.3 VideoCheckFinalPlayer — 主视频与预览条里的多个 `<video>`

**位置**: `src/components/video-check/VideoCheckFinalPlayer.tsx`  
**逻辑**: 主视频用 `videoRef`，进度条里 `clips.map` 渲染多个 `<video ref={previewVideoRefs.current[i]}>`。已有在 `autoPlay === false` 时清空所有 preview 的 `src` 的 effect。

**问题**: 组件**卸载**时没有统一清理：主视频和 preview 列表若在 `autoPlay=true` 时离开页面，不会走“清空 src”的逻辑，这些节点从 DOM 移除后变成 Detached，且仍持有解码缓冲。

**修复**: 增加仅执行一次的 unmount effect，在 return 中对 `videoRef.current` 和 `previewVideoRefs.current` 中每个元素执行 `pause()`、`src = ""`、`load()`。

---

### 1.4 ExplorePage — 网格里的多个 `<video>`

**位置**: `src/components/ExplorePage.tsx`  
**逻辑**: `videoRefs.current[index]` 指向网格中每个卡片的 `<video>`，用于 hover 时 pause。

**问题**: 组件卸载时没有对 ref 里的 video 做释放，离开页面后这些 video 从 DOM 移除变成 Detached，仍占显存/内存。

**修复**: 增加 unmount effect，在 cleanup 中遍历 `videoRefs.current`，对每个执行 `pause()`、`src = ""`、`load()`。

---

### 1.5 列表/对话中的大量 `<video>`（MessageArea、ShotsSection、LazyShotsSection 等）

**位置**:  
- `MessageArea.tsx`: `msg.event_data.video_files.map` 里直接写 `<video><source src=...>`  
- `ShotsSection.tsx` / `LazyShotsSection.tsx`: 每个 shot 的每个 version 可能一个 `<video>`  
- `TaskDetailModal`、`UserInputsManagement`、`VideoHistorySection` 等也有多处 `<video>`

**问题**: 这些是正常 DOM 内的 video，但当列表滚动、切换会话、关闭弹窗时，对应组件卸载，video 从 DOM 移除后变成 Detached。若未在卸载时清空 `src` 并 `load()`，解码器缓冲会一直保留。

**修复建议**:  
- 短期：先修复上述 1.1–1.4 的“主动创建或集中管理”的 video，对整体 Detached 数量影响最大。  
- 中期：抽一个通用组件或 hook（如 `useVideoElementCleanup(ref)`），在 unmount 时对 ref 指向的 video 执行 `pause(); el.src = ""; el.load();`，在 MessageArea、ShotsSection、LazyShotsSection 等列表/详情中的 `<video>` 上统一使用。

---

## 2. Detached Window / Detached DOM（44% Retained）

可能来源包括：

- **Radix Dialog/AlertDialog**：通过 Portal 挂到 body，关闭时若父组件或全局某处仍持有对 Dialog 内容、内部 state 或 ref 的引用，已关闭的窗口对应的 DOM 树会变成 Detached。
- **createPortal**：如 `ImmerseShareChatDialog.tsx` 使用 `createPortal`，若 portal 根节点或内部节点被某 ref/闭包长期引用，也会形成 Detached。
- **TaskDetailModal / 各类 Dialog**：内容里大量嵌套（任务详情、keyframes、videos 等），若 Modal 关闭后其 state 或子组件 ref 仍被保留，整块 DOM 会滞留。

**建议**:  
- 用 Chrome DevTools Memory 的 “Allocation instrumentation” 或 “Heap snapshot” 对比打开/关闭 Dialog 前后，看 Detached Window 的保留路径（Retainers）。  
- 确保 Dialog 的 `onOpenChange(false)` 时清空内部 state、不保留对已关闭内容节点的 ref；避免在模块级或 Context 里长期持有 Dialog 内部 DOM 或大对象。

---

## 3. 游离事件监听器（1 万+）

- 多数 `addEventListener` 已在对应 `useEffect` 的 return 里配了 `removeEventListener`（如 CreateVideoPage、VideoCheckFinalPlayer、ShotsCheckPage 等）。  
- 可能问题点：  
  1. **闭包/引用不一致**：effect 每次用新的 handler 引用，但 cleanup 里用旧引用调用 `removeEventListener`，导致删不掉，重复挂载会不断累加。  
  2. **未做 cleanup 的监听**：个别地方只在 mount 时 `addEventListener`，未在 unmount 或 deps 变化时 `removeEventListener`。  
  3. **动态创建的元素**：如 ShotsCheckPage 里为每个 shot 创建的 video，在 effect 里 `video.addEventListener('canplay', ...)`，若 effect 没有正确 cleanup（或 video 未释放），这些监听会一直挂在 Detached 节点上，被算进“游离监听器”。

**建议**:  
- 先完成对 ShotsCheckPage、VideoCheckCanvasPage 等处的 video 与 effect 的 cleanup 修复，减少 Detached 节点，再重拍快照看监听器数量是否明显下降。  
- 对仍存在的监听泄漏，在 DevTools 里对 “Detached EventListener” 做 “Reveal in Summary” 查 Retainer，对应到具体组件/effect 再补 cleanup 或统一用 ref 保存 handler 保证 remove 时引用一致。

---

## 4. 修复优先级小结

| 优先级 | 位置 | 问题 | 修复 |
|--------|------|------|------|
| P0 | ShotsCheckPage | 每 shot 一个 createElement video，无 cleanup | effect cleanup 中释放所有已创建 video（removeEventListener + src="" + load） |
| P1 | VideoCheckCanvasPage | createElement video 仅移除监听，未释源 | cleanup 中 video.src="" ; video.load() |
| P1 | VideoCheckFinalPlayer | 卸载时未释主视频与 preview 列表 | unmount effect 中统一 pause + src="" + load |
| P1 | ExplorePage | 卸载时未释网格内 video refs | unmount effect 中遍历 videoRefs 释放 |
| P2 | MessageArea / ShotsSection 等 | 列表/详情中 video 卸载未主动释源 | 引入 useVideoElementCleanup 或包装组件，在 unmount 时清空 video |

完成 P0/P1 后建议再拍一次 Memory 快照，对比 Detached `<video>` 数量与整体 Retained Size 是否明显下降。

---

## 5. 显存级释放（进阶修复，已落地）

为避免「仅从 DOM remove、显存不释放」的问题，已统一采用**显存级释放**：

- **`src/utils/videoCleanup.ts`**  
  - `hardCleanupVideo(el)`: 对单个 `HTMLVideoElement` 执行 `pause()` → `src = ""` → `removeAttribute("src")` → `load()`，让解码器释放缓冲。

- **`src/components/ui/VideoWithCleanup.tsx`**  
  - 包装 `<video>`，在**组件卸载**时对内部 ref 调用 `hardCleanupVideo`，用于列表、弹窗等会频繁挂载/卸载的 video。

- **已应用位置**  
  - 所有带 `videoRef` / `previewVideoRefs` / `videoRefs` 的页面：卸载时调用 `hardCleanupVideo`（VideoCheckFinalPlayer、ExplorePage、ImmersiveVideoPlayer、ExploreVideoPlayer）。  
  - 列表/详情中的 `<video>` 已改为 `<VideoWithCleanup>`：MessageArea（video_files）、ShotsSection、LazyShotsSection、VideoSegmentsSection、LipsyncSection、VideoAssemblySection。  
  - createElement 的 video：ShotsCheckPage、VideoCheckCanvasPage、FilePreview 的 effect 清理中先 removeEventListener，再 `hardCleanupVideo(video)`。

- **注意**  
  - 避免在全局（如 `window.xxx`）或 Store 中持有 video 实例。  
  - 异步回调（如 onTimeUpdate、Promise）若未在卸载时取消，会通过闭包继续引用 video，需在 effect cleanup 中移除监听或取消 Promise。
