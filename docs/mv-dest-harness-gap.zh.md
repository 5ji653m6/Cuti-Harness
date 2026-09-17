# `$mv`：dest vs 现在 harness（讨论稿）

[English](mv-dest-harness-gap.md) | 中文

> 状态：看板里「已做」的已经改了代码。划掉的 = 已拍板不用做。 日期：2026-09-05。 对照：dest 备份 `origin/archive/pre-harness-dev`（`82f910a`，8-30）vs 当前 `deepseek-harness`（`5663485`）。 若 8-30 之后只改了线上 dest、没回这个 archive，那些改动这份对不上。

前提：本地 compose **开了** `VIDEO_CONTINUOUS_PLAN_PATCH_ENABLED`。不跑 `compile_mv`。顺序和参数靠 `$mv` / `$h3` 等 skill，和 dest 一样。

---

## 方案看板

| 项 | 结论 |
|---|---|
| 字幕：`$hyperframes-captions` 改回 dest「LLM 写 `caption_html`」 | **已做** |
| 参数合同：dest `video_urls` / `images` vs plugin `video_steps` / `*_from_step` | **已做**：plugin + schema **两套都认** |
| `$mv` / `$video-research` 写了 `web_search`，tool-video 没有 | **已做**：video preset 挂上 `dsh-tool-web` |
| ~~`compile_mv` 把 H3 从 1080p 改成 768p/2k~~ | **不用。** continuous 不跑 compiler；分辨率看 LLM 有没有按 `$h3` 写 |
| ~~continuous 加「第一批必须是歌/分析/切」政策 / 恢复 `_validate_mv_compat_plan`~~ | **不用。** dest 也是 skill 管顺序，不是 compiler 硬拦 |
| ~~checkpoint 硬 load `suno-song` / `h3` / captions（frontmatter dependencies）~~ | **不用。** dest 也是正文里 `video_skill_load`，模型自觉 load |
| ~~改 `compile_mv` 默认 `caption-highlight` / 没 HTML 不烧字~~ | **不用。** continuous 不跑 compiler，字幕留给 LLM `add_tasks` |
| ~~字幕方案 A 两个 skill / B 一份 skill 两种 mode~~ | **不用。** 已拍板整份改回 dest HTML（原方案 C） |
| 8-30 之后线上 dest 还有没有没进 archive 的改动 | 未确认 |

---

## 0. 先记住的结论

`$mv` 导演手册、`$suno-song`、`$h3`、`reference.md`、`$video-research`、`$subtitle-authoring` **基本是 dest 原文**（`load_skill` 改成了 `video_skill_load`）。

真正还拉开过、**已经按拍板改了** 的是：

1. **字幕 skill**：`$hyperframes-captions` 改回 dest「写 `caption_html`」。
2. **continuous 执行**：plugin + schema 同时认 dest URL 和 `*_step`。见 §2。
3. **`web_search`**：video preset 挂上 `@deepseek-ai/dsh-tool-web`。

~~`compile_mv` 塞 1080p、先音乐后画面的 compiler 校验~~：这条路上不存在，见看板。

---

## 1. 字幕：别人用吗？改回去会不会误伤？

### 1.1 现在仓库里谁在用 HyperFrames 字幕

**Workflow 正文里点名走这条的，目前只有 `$mv`。**

| 调用方 | 怎么用 | 是不是 dest「LLM 写 HTML」 |
|---|---|---|
| `$mv` SKILL 第 8 步 | load `hyperframes-captions`，交 `caption_html` | **是，dest 产品** |
| `$hyperframes-captions` SKILL | 写完整 `caption_html`，按需 load core/media/animation | **是，已改回 dest** |
| ~~`compile_mv` / `WorkflowPlanBuilder.finish(captions=True)` 默认 `caption-highlight`~~ | continuous **不跑** | 不用改 compiler |
| 后期 Plan Patch 目录 | `media.hyperframes_caption` 绑 `skill_id=hyperframes-captions` | 跟同事 skill：选 style |
| `$seedance2` / 产品流 SKILL | **没有**写 HyperFrames 成片字 | 不用这条 |
| `$subtitle-authoring` | 静态 SRT + `subtitle_burn` | 另一条后期 |

media-service **一条 API 两条腿**都还在：

- 有 `caption_html` / `composition_html` → 用 LLM 写的 HTML 渲染（你 dest 那条）。
- 都空 → 按 `style` **生成**句级 HTML 再渲染（同事灌词）。

打架的是 **skill 说明书**（`$mv` 教写 HTML，captions skill 禁止只写 HTML）。

### 1.2 「改过去」会伤谁

把 **`$hyperframes-captions` 改回 dest HTML**：

- `$mv` 对齐。
- 副作用（**已接受**）：用户直接 `$hyperframes-captions`、后期 Plan Patch 烧动态字幕，也会变成「先写 HTML」。没有第二个 workflow 依赖灌词。静态字幕仍走 `$subtitle-authoring`。

~~把 capability 改成 `caption_html` required、删掉 style 灌词腿~~：不必。执行层可以继续两腿，skill 不许走「没 HTML 也算完成」。

### 1.3 方案

- ~~**A. 两个 skill**：dest 作者 skill + 留下 style 灌词 `$hyperframes-captions`~~
- ~~**B. 一个 skill 里写两种 mode**~~
- **C. 整份改回 dest HTML（已拍板 2026-09-05）**
  - `$hyperframes-captions` 改回 archive 那版：写完整 `caption_html`，按需 load core/media/animation/registry；Never「只报 style 名让服务灌词」。
  - `$mv` 第 8 步已经是 dest 文案，和 skill 对齐即可。
  - capability 可以继续两腿（有 HTML 用 HTML，没有才 style），但 skill / `$mv` 不许「没 HTML 也算完成」。
  - 测试里「无 HTML 就 `caption-highlight`」要改成 dest 合同。

---

## 2. 参数合同（还要做）

### 2.1 LLM 会写 parameter，也会跑 capability

```text
LLM add_tasks（capability + parameters）
    → Runtime 校验、追加到 plan
    → execute_build 按 capability 名字找处理函数
    → 处理函数读 parameters，去调 ffmpeg / H3 / Suno
```

会写参数，也会跑。不是少了一步。

### 2.2 同名 capability ≠ 同一份代码

仓库里 **`media.concat` 有两套执行代码**，读的字段不同：

| 谁跑 | 文件 | 它从 parameters 里拿什么 |
|---|---|---|
| **dest 当年** | `chat/v2/executors.py` | **`video_urls`**（没有则用选中的 artifact URL） |
| **现在 build** | `builtin_plugins/media_core.py` | **`video_steps`**（上一步的 step_id，再换成 URI） |

`$mv` skill 还在教 dest 那套：`media.concat` 传 **`video_urls`**。 现在 `execute_build` 走 **media_core**，**只看 `video_steps`**。传了 `video_urls` 当没看见。 `video_urls` 是 **最后调 ffmpeg 时** 程序自己填的，不是让 LLM 填的。

改的只是「文件从哪来」那几个键，不是整个 capability 只剩 step：

| 现在 plugin 认的 | dest 大致对应 |
|---|---|
| `video_step` / `video_steps` | `video_url` / `video_urls` |
| `audio_step` | `audio_url` |
| `source_video_step` | 抽帧用的 `video_url` |
| `media_step` | probe 用的媒体 URL |
| `subtitle_step` | 字幕文件 |
| `transcription_step` / `analysis_step` | 上一步转写/分析产物 |
| `reference_from_steps` 这类 | H3 的 `images` / `audios` |

`prompt`、`duration`、`model`、`resolution`、`tags`、`normalize`、`transition_duration`、`caption_html` **没改成 step**。

`images`：plugin 用 `setdefault`，LLM 若已经塞了可用 URL，H3 **有可能**直接工作。 concat / mix / 字幕 **没有**这层兼容。

后期 `preview_plan_patch` 有一层：禁止 LLM 写 `*_url` / `*_step`，改由 `inputs[]` 填成 `video_steps`。 **continuous 的 `add_tasks` 没有这层映射。**

### 2.3 用一次 concat 看完

LLM 按 dest skill 交：

```json
{
  "capability_id": "media.concat",
  "parameters": { "video_urls": ["https://cdn/.../a.mp4", "https://cdn/.../b.mp4"] }
}
```

schema 可能过（还要求 `video_urls`）。`execute_build` → media_core → `video_steps` 缺省 `[]` → 没有片子可拼。

写成 Runtime 合同才能跑：

```json
{
  "capability_id": "media.concat",
  "parameters": { "video_steps": ["shot-1-video", "shot-2-video"] },
  "depends_on": ["shot-1-video", "shot-2-video"]
}
```

`video_step` = 上一步产出文件的名字。Runtime 表：`shot-1-video → uri`。plugin 查表再交给 ffmpeg。

dest 用 URL：一步跑完才调下一步，tool 返回里已经有 URL。 harness 用 step：计划提交时下一镜 URL 往往还不存在。

### 2.4 可以怎么改（已拍板：方案 3）

1. ~~改 skill 正文，废弃 dest URL~~
2. ~~continuous 提交时只翻译成 step，禁止裸 URL~~
3. **plugin + json schema 同时认两套 key（已做）**：`video_urls` 或 `video_steps`，`images`/`audio_url` 或 `*_from_step` / `*_step`。LLM 可继续抄 dest，compiler 路径也不破。

---

## 3. ~~H3 768p / `compile_mv` 塞 1080p~~（不用改）

本地 flag 开着，创建 `$mv` **不跑 `compile_mv`**。没有程序把 `spec.resolution=1080p` 写进 H3 步骤。分辨率只看 LLM `add_tasks` 有没有按 `$h3` 写 `768p` / `2k`。

~~改 `compile_mv` 默认 1080p~~：只在关 flag / EKS overlay 还走 compiler / compiler 单测里才有意义。当前这条 continuous **不动 compiler。**

模型没 load `$h3` 或乱填 `1080p`，Runtime 现在不会拦。和 dest 一样靠 skill，**不加硬校验。**

---

## 4. ~~先音乐后画面 / `_validate_mv_compat_plan`~~（不用改）

dest Never（写在 `$mv` 里，不是 Python）：没听分析不许切、不许先出视频再塞歌、H3 要图、即梦不许 `audios`。

`_validate_mv_compat_plan` 是 harness **compiler** 冻整张 DAG 时的门禁。continuous 初始化只有 intent，没有那张图，校验没对象。模型一批一批 `add_tasks`，更接近 dest。

Runtime 仍会拦：capability 不在白名单、一批超过 8 个、依赖还没跑完。 **不会**拦「第一批必须是歌」。dest 当时也拦不了。

~~continuous 加政策门禁 / 恢复「第一批必须是歌」~~：**不用。** 用 skill 控制。

---

## 5. 其它

已做：

- §2 参数合同：media_core / capability schema 两套 key 都认。
- video preset 挂上 `web_search`（`@deepseek-ai/dsh-tool-web`）。
- `$hyperframes-captions` 改回 dest HTML。

~~`$mv` frontmatter 声明 `suno-song` / `h3` / captions，checkpoint 硬 load~~：**不用。** 正文已经 `video_skill_load(...)`，dest 也是这样。
