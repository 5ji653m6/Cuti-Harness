# 「工具与参数 / 依赖图 / Metrics」使用现状

## 你说的「那个 component」指什么

- **工具与参数** + **Metrics**：在 `ConsistencyShotCard.tsx` 里是 **ToolAndMetricsBlock**（工具与参数、原因、错误、Metrics 一起）。
- **依赖图**（参考图 + 角色版本）：目前**没有**做成和 ToolAndMetricsBlock 同一级别的共用组件；只有 TaskDetailModal 里内联了「依赖」区块。

所以：  
- 真正共用的只有 **ToolAndMetricsBlock**（工具与参数 + 原因/错误 + Metrics）。  
- 「依赖图」只在任务详情里有，且是内联写的，**没有**抽成和 (1)(2) 共用的 component。

---

## 三处使用情况

| 场景 | 用的组件 | 工具与参数 | Metrics | 依赖图 | 一致性尝试详情 |
|------|----------|------------|---------|--------|----------------|
| **1. 运行历史结果详情**（一致性测试结果弹窗） | **ConsistencyShotCard** (variant=result) | ✅ ToolAndMetricsBlock | ✅ ToolAndMetricsBlock | ❌ **没有** | ✅ DisplayLinesBlock |
| **2. 候选详情**（从 thread 拉取 → 点「详情」Sheet） | **ConsistencyShotCard** (variant=detailOnly) | ✅ ToolAndMetricsBlock | ✅ ToolAndMetricsBlock | ❌ **没有** | ✅ DisplayLinesBlock |
| **3. 视频历史记录 → 按镜头展示 tab** | **TaskDetailModal** 内联 | ✅ 有（内联，**不是** ToolAndMetricsBlock） | ✅ 有（内联） | ✅ 有（内联「依赖」） | ✅ ConsistencyBlock（本地，和 DisplayLinesBlock 逻辑类似） |

结论：

- **1 和 2**：用的是**同一个** component（ConsistencyShotCard），里面是 **ToolAndMetricsBlock** + DisplayLinesBlock，**没有**依赖图。
- **3**：**没有**用 ConsistencyShotCard，是 TaskDetailModal 里自己写的 工具与参数 + Metrics + 依赖 + ConsistencyBlock，所以和 1、2 **不是**同一个 component。

---

## 缺什么（你感觉「缺少点」可能指这些）

1. **依赖图只在 (3) 有**
   - 运行历史结果详情、候选详情 都没有「依赖」区块。
   - 若希望 1、2 也能展示参考图/角色版本，需要在 **ConsistencyShotCard** 里加可选「依赖」区块（如 `reference_image_urls`、`character_version_ids`），并在 运行结果/候选 传对应数据。

2. **(3) 没有用同一套 component**
   - 按镜头展示 tab 的「工具与参数 + Metrics + 依赖」是 TaskDetailModal 内联写的，和 ConsistencyShotCard 的 ToolAndMetricsBlock 不是同一套。
   - 若希望三处完全一致（样式、结构、一处改三处生效），需要把 TaskDetailModal 里那一段改成用 **ConsistencyShotCard** 或抽一个共用块（工具与参数 + Metrics + 可选依赖图）。

3. **一致性展示有两份实现**
   - ConsistencyShotCard 里：**DisplayLinesBlock**。
   - TaskDetailModal 里：**ConsistencyBlock**（本地组件，逻辑和 DisplayLinesBlock 类似）。
   - 若追求完全一致，可考虑让 TaskDetailModal 也用 DisplayLinesBlock（或把 ConsistencyBlock 抽到公共组件里，两处都用）。

---

## 小结

- **是**用「工具与参数 + Metrics」这套的：**1. 运行历史结果详情**、**2. 候选详情**（通过 ConsistencyShotCard 的 ToolAndMetricsBlock）。
- **不是**用同一 component 的：**3. 视频历史 按镜头展示 tab**（自己内联的一套）。
- **缺少**的：  
  - 1、2 没有**依赖图**；  
  - 3 没有用和 1、2 同一的 **ToolAndMetricsBlock / 同一 component**。

如果你愿意，下一步可以：  
- 在 ConsistencyShotCard 里加可选「依赖图」并在 1、2 传数据；和/或  
- 在 TaskDetailModal 按镜头展示里改用 ConsistencyShotCard 或抽成「工具与参数 + 依赖图 + Metrics」一个共用组件，让三处真正用同一套。
