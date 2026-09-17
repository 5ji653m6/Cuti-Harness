# `$mv`: dest versus the harness (discussion draft)

English | [中文](mv-dest-harness-gap.zh.md)

> Status: items marked “done” on the board are implemented. Struck-through items were rejected. Date: 2026-09-05. Comparison: dest backup `origin/archive/pre-harness-dev` (`82f910a`, August 30) versus `deepseek-harness` (`5663485`). Production-only dest changes after August 30 are not covered by this comparison.

Assumption: local compose **enables** `VIDEO_CONTINUOUS_PLAN_PATCH_ENABLED`. It does not run `compile_mv`. Skills such as `$mv` and `$h3` guide ordering and parameters, as in dest.

---

## Decision board

| Item | Decision |
|---|---|
| Captions: restore dest's “LLM writes `caption_html`” in `$hyperframes-captions` | **Done** |
| Parameter contract: dest `video_urls` / `images` versus plugin `video_steps` / `*_from_step` | **Done**: plugin and schema accept **both** |
| `$mv` / `$video-research` mention `web_search`, missing from tool-video | **Done**: video preset mounts `dsh-tool-web` |
| ~~Change H3 from 1080p to 768p/2k in `compile_mv`~~ | **Not needed.** Continuous execution does not run the compiler; resolution depends on following `$h3` |
| ~~Require song/analysis/cut in the first continuous batch; restore `_validate_mv_compat_plan`~~ | **Not needed.** dest also uses Skill instructions rather than a compiler rule |
| ~~Force checkpoint loading of `suno-song` / `h3` / captions through frontmatter dependencies~~ | **Not needed.** dest also relies on model-initiated `video_skill_load` from the body |
| ~~Change `compile_mv`'s default `caption-highlight`; refuse captions without HTML~~ | **Not needed.** Continuous execution leaves caption `add_tasks` to the LLM |
| ~~Caption option A: two Skills; B: two modes in one Skill~~ | **Not needed.** Restore the entire dest HTML approach (option C) |
| Production dest changes after August 30 missing from the archive | Unconfirmed |

---

## 0. Main conclusion

The `$mv` director guide, `$suno-song`, `$h3`, `reference.md`, `$video-research`, and `$subtitle-authoring` are **largely the dest originals**, with `load_skill` renamed to `video_skill_load`.

The divergences addressed by the accepted changes are:

1. **Caption Skill**: `$hyperframes-captions` again asks the model to write `caption_html`.
2. **Continuous execution**: plugins and schemas accept both dest URLs and `*_step` references. See §2.
3. **`web_search`**: the video preset mounts `@deepseek-ai/dsh-tool-web`.

~~`compile_mv` injecting 1080p and requiring music before visuals~~: this compiler path is not used here; see the board.

---

## 1. Captions: consumers and compatibility

### 1.1 HyperFrames caption consumers

**Only `$mv` explicitly names this path in its Workflow body.**

| Caller | Usage | dest-style “LLM writes HTML”? |
|---|---|---|
| `$mv` SKILL step 8 | Load `hyperframes-captions`, submit `caption_html` | **Yes, dest product** |
| `$hyperframes-captions` SKILL | Write complete `caption_html`; load core/media/animation as needed | **Yes, restored to dest** |
| ~~`compile_mv` / `WorkflowPlanBuilder.finish(captions=True)` default `caption-highlight`~~ | Continuous execution **does not run it** | No compiler change needed |
| Post-production Plan Patch catalog | `media.hyperframes_caption` binds `skill_id=hyperframes-captions` | Colleague Skill path: choose a style |
| `$seedance2` / product Workflow Skills | **Do not** specify HyperFrames final captions | Do not use this path |
| `$subtitle-authoring` | Static SRT + `subtitle_burn` | Separate post-production path |

Media Service retains **two implementations behind one API**:

- With `caption_html` / `composition_html`: render the model-authored HTML (dest path).
- Without either: **generate** sentence-level HTML from `style`, then render (colleague path).

The conflict was in the **Skill instructions**: `$mv` asked for HTML while the captions Skill prohibited HTML-only input.

### 1.2 Impact of restoring the dest approach

Restoring **dest HTML authoring in `$hyperframes-captions`**:

- Aligns `$mv`.
- Has an **accepted** consequence: direct `$hyperframes-captions` use and dynamic-caption post-production also require writing HTML first. No other Workflow depends on style-only authoring. Static subtitles still use `$subtitle-authoring`.

~~Make `caption_html` mandatory in the capability and remove style-based generation~~: unnecessary. Both execution paths can remain, while the Skill must not claim success without HTML.

### 1.3 Options

- ~~**A. Two Skills**: dest authoring plus the style-based `$hyperframes-captions`~~
- ~~**B. Two modes in one Skill**~~
- **C. Restore the full dest HTML approach (accepted September 5, 2026)**
  - Restore the archived `$hyperframes-captions` instructions: complete `caption_html`, optional core/media/animation/registry loading; never report only a style name and delegate text insertion.
  - `$mv` step 8 already follows dest wording; align the caption Skill.
  - The capability may retain both execution paths, but `$mv` and the Skill cannot claim completion without HTML.
  - Tests expecting `caption-highlight` without HTML must follow the dest contract.

---

## 2. Parameter contract (work identified)

### 2.1 The LLM writes parameters and schedules capabilities

```text
LLM add_tasks（capability + parameters）
    → Runtime 校验、追加到 plan
    → execute_build 按 capability 名字找处理函数
    → 处理函数读 parameters，去调 ffmpeg / H3 / Suno
```

Both parameter generation and execution exist; neither step is missing.

### 2.2 The same capability name does not mean the same implementation

The repository has **two implementations of `media.concat`**, reading different fields:

| Path | File | Parameters read |
|---|---|---|
| **Original dest** | `chat/v2/executors.py` | **`video_urls`**, otherwise selected artifact URLs |
| **Build execution** | `builtin_plugins/media_core.py` | **`video_steps`**, resolved from prior step IDs to URIs |

The `$mv` Skill teaches dest's **`video_urls`**. At the compared baseline, `execute_build` used **media_core**, which only read **`video_steps`**, ignoring `video_urls`. The program supplied `video_urls` at the final FFmpeg call, not from the LLM input.

Only the file-source keys differ; not every parameter becomes a step:

| Plugin field | Approximate dest field |
|---|---|
| `video_step` / `video_steps` | `video_url` / `video_urls` |
| `audio_step` | `audio_url` |
| `source_video_step` | `video_url` for frame extraction |
| `media_step` | Media URL for probing |
| `subtitle_step` | Subtitle file |
| `transcription_step` / `analysis_step` | Prior transcription/analysis artifact |
| `reference_from_steps` | H3 `images` / `audios` |

`prompt`, `duration`, `model`, `resolution`, `tags`, `normalize`, `transition_duration`, and `caption_html` **remain ordinary parameters**.

For `images`, the plugin uses `setdefault`, so H3 **may** work if the LLM already supplied usable URLs. Concat, mix, and captions lacked that compatibility at the compared baseline.

Post-production `preview_plan_patch` prohibits LLM-authored `*_url` / `*_step` and maps `inputs[]` to `video_steps`. **Continuous `add_tasks` does not use that mapping.**

### 2.3 One concat example

The LLM follows the dest Skill:

```json
{
  "capability_id": "media.concat",
  "parameters": { "video_urls": ["https://cdn/.../a.mp4", "https://cdn/.../b.mp4"] }
}
```

The schema may accept this, even requiring `video_urls`; `execute_build` then reaches media_core, where missing `video_steps` defaults to `[]`, leaving no clips to join.

The Runtime-oriented request is:

```json
{
  "capability_id": "media.concat",
  "parameters": { "video_steps": ["shot-1-video", "shot-2-video"] },
  "depends_on": ["shot-1-video", "shot-2-video"]
}
```

`video_step` identifies a producing step. Runtime stores `shot-1-video → uri`; the plugin resolves it before calling FFmpeg.

dest uses URLs because the prior call already returned one. The harness uses steps because a future shot URL often does not exist at planning time.

### 2.4 Options (option 3 accepted)

1. ~~Rewrite Skill bodies and remove dest URL parameters~~
2. ~~Translate only to steps at continuous submission; prohibit raw URLs~~
3. **Accept both key sets in plugins and JSON schemas (done)**: `video_urls` or `video_steps`, `images`/`audio_url` or `*_from_step` / `*_step`. The LLM can follow dest while compiler paths remain compatible.

---

## 3. ~~H3 768p / `compile_mv` injecting 1080p~~ (no change)

With the local flag enabled, creating `$mv` **does not run `compile_mv`**. No compiler writes `spec.resolution=1080p` into H3 steps. Resolution depends on the LLM following `$h3` and supplying `768p` / `2k` in `add_tasks`.

~~Change the `compile_mv` default~~: relevant only with the flag disabled, compiler-based EKS overlays, or compiler unit tests. The continuous path **does not change that compiler**.

If the model omits `$h3` or supplies `1080p`, Runtime has no such guard at this baseline. Like dest, it relies on the Skill; **no hard validation is added**.

---

## 4. ~~Music before visuals / `_validate_mv_compat_plan`~~ (no change)

dest's prohibitions live in `$mv`, not Python: do not cut before music analysis, do not create video before fitting the song, H3 requires images, and Seedance must not receive `audios`.

`_validate_mv_compat_plan` validates a complete compiler-authored DAG. Continuous initialization contains only intent, so that graph does not exist. Model-authored batches of `add_tasks` are closer to dest.

Runtime still checks capabilities against the allowlist, batches exceeding eight tasks, and unfinished dependencies. It does **not** require the first batch to generate music; dest did not enforce that either.

~~Add a continuous policy gate requiring music first~~: **not needed**; use Skill guidance.

---

## 5. Other items

Completed:

- §2: media_core and capability schemas accept both parameter sets.
- The video preset includes `web_search` (`@deepseek-ai/dsh-tool-web`).
- `$hyperframes-captions` follows dest HTML authoring.

~~Declare `suno-song` / `h3` / captions in `$mv` frontmatter and force checkpoint loading~~: **not needed**. The body already calls `video_skill_load(...)`, as dest does.
