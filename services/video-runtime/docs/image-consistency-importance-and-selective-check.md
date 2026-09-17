# 关键帧 I2I 角色一致性：按「是否需要检查」选择性输出（Prompt 优先方案）

## 1. 背景与问题

- 同一张关键帧可能带 **多张参考图** + **prompt 里多名角色**（主角 + 伴舞 + 朋友群像）。
- 当前做法倾向于 **每个逻辑角色一条 `per_character`**，且脸档与主角同严 → **群像 / 单张群 ref 复制到多人** 时容易 **多轮重试**，但最后又靠 **放宽文案或滥用 `face: n_a`** 过关。
- 产品上也常 **不需要** 对远景人群、氛围舞者做 **「必须同一张 ref 脸」** 级别的校验。

## 2. 目标（本方案）

1. **先在 prompt 侧** 让 VLM **自行判断**：哪些角色在本张生成图里 **需要做「人设硬对齐」（脸/配饰/服装等 vs 对应参考图）**。
2. **`per_character` 只包含「需要检查」的角色**；**不需要的就不要出现**（不强行比对、不误杀重试）。
3. **整图离谱异常**（`severe_abnormality` 等）**不受影响**：无论是否列入 `per_character`，都要看全图。

> 说明：长期仍可与「上游 `consistency_tier` 字段」叠加以防模型漏检；本文件先落地 **纯 prompt 的选择性输出**，改动面最小。

## 3. 行为约定（给实现/评审用）

| 项目 | 约定 |
|------|------|
| `has_character` | 仍为：是否存在 **至少一个** 需要做严格人设对齐的角色。**若仅做全图画面质量检查、无任何角色需对齐**，则为 `false`，`per_character=[]`，但 **整图 `severe_abnormality`（含轻伪影与事故）仍必填**。 |
| `per_character` | **仅**包含「需要严格对齐参考」的角色条目；**不要为了凑齐 prompt 里的所有名词都开一条**。 |
| 未列入的角色 | **不要**在 `per_character` 里用「路人」「氛围舞者」占一条并写 `n_a` 糊弄；**直接省略**。 |
| 参考图 legend | Human 仍可附多图说明；模型应结合 **构图（脸是否可见、是否主体）** 与 **prompt 语义** 决定谁该进 `per_character`。 |

## 4. 何时「需要」进 `per_character`（VLM 判定准则）

**建议写入一致性 mustache，供模型遵守：**

- **需要（应输出一条）：**
  - prompt / legend 明确 **image k 对应某具体角色**，且成片中该主体 **面部或标志性外观** 可用于比对，且产品期望 **认人一致**。
  - 画面 **中近景主角、面孔清晰**，且参考图为此人 **定妆/主图**。
- **不需要（不要输出该角色）：**
  - **群像 / 多名伴舞**：仅要求 **服装风格、时代感、人数级** 与参考 **氛围** 一致，**无「每张脸必须同 ref」** 的产品要求。
  - **远景、背影、剪影、糊到小**：可比对信息不足，且 **不是叙事认人重点**。
  - **群众、匿名舞者**：prompt 仅为「人群狂欢」「背景舞动」等 **泛称**。

**冲突处理**：若 prompt 写「四名伴舞与 image 2 **面部**完全一致」而产品又希望放松 —— 属于 **产品/上游 prompt 问题**；本检查器可按「prompt 显式写死要脸一致」**仍将伴舞纳入 `per_character`**。否则按上表 **可不列入**。

## 5. Prompt 适配片段（粘贴进 `video_character_consistency_check.mustache`）

以下块建议放在 **`has_character_decision` 之后**、`evaluation_dimensions` 之前（或与 `evaluation_dimensions` 开头合并），并与现有「忌见人就检」条目不矛盾：**这里是从「全检所有人」收束为「只检该检的」**。

```markdown
<selective_per_character priority="critical">

**选择性输出 `per_character`（与 has_character 配合）**

- 在通读 **generation_prompt、reference_images_legend、生成图** 之后，**自行判断**哪些角色在本张图里 **必须** 做「与对应参考图的人设硬对齐」（脸 / 配饰 / 服装 / 体型 / 发型 / 风格表现）。
- **`per_character` 数组只包含这些角色**；每个条目对应一个 **清晰的比对主体**（可写在 `name` 里，与 legend 中的称呼一致）。
- **不要**为了覆盖 prompt 里提到的每一个群体词（如「四名伴舞」「朋友们」「人群」）都强行新增一条；**仅当**你真的要以「同一张参考脸 / 同一套指定人设」为标准去卡质量时，才新增条目。
- **氛围/群像/远景舞者**：若业务上只要求 **造型与场景氛围**、不要求 **逐人同源**，则 **不要** 把这些写进 `per_character`（避免无谓 fail）。是否属于此类，结合 **脸在画中是否清晰占主**、**prompt 是否硬绑定「与 image N 面部一致」** 判断。
- **禁止**用「新建一条 + 全体 `n_a`」来替代「不需要检查就不列出」—— **不需要检查的，直接省略该角色**。
- **has_character**：当且仅当 **`per_character` 非空**（至少有一个角色要做上述硬对齐）时为 `true`；若本张图 **没有任何** 角色需要这种对齐、仅需看整图质量，则 `has_character=false` 且 `per_character=[]`，**仍须**完整填写 **`severe_abnormality`、`severe_abnormality_reason`、`reason`**（全图维度不因人设未检而跳过）。

</selective_per_character>
```

**Human 末尾可加一句提示：**

```markdown
输出前请确认：`per_character` 仅含「需硬对齐参考」的角色；其余角色勿列入。全图仅评 **`severe_abnormality`**（合并了原整图 artifact 与严重异常）。
```

## 6. 与后端 `passed` 的关系（当前逻辑，便于对接）

- **`has_character=false`**：`passed` 由 **整图 `severe_abnormality`** 决定，`per_character` 不参与。
- **`has_character=true`**：`passed` = 现有 **各条 `per_character` 聚合** + 整图 `severe_abnormality`。

因此：**少列 `per_character`** → **少挡 pass**；**离谱图** 仍能被 **`severe`** 拦住。

## 7. 风险与后续加固

| 风险 | 缓解 |
|------|------|
| VLM 漏列本应严检的主角 | legend 中增加 **`consistency_tier: primary`must 出现在 `per_character`**（二期，由上游写入 label）。 |
| VLM 把该检的伴舞全省略 | prompt 中若 **明确**「与 image N 面部一致」，指令要求 **仍将绑 ref 的主体列入**。 |
| 与旧数据对比metrics 含义变化 | `consistency_details` 里 `per_character` 条数可能变少，属预期；统计时看 **attempts** 与 **severe** 单列。 |

## 8. 建议落地顺序

1. 将 **§5** 块并入 `video_character_consistency_check.mustache`，并微调与现有 `has_character_decision` 的措辞避免重复。
2. 观察 dev：**同 thread 重试次数**、**`per_character` 平均条数**。
3. 若漏检率高：再在 `reference_image_labels` 增加 `consistency_tier`，与 §7 联动。

---

*文档版本：与「按角色重要性」讨论对齐；优先 prompt 选择性输出，后续可叠加上游 tier。*
