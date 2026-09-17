---
name: hyperframes-captions
description: 成片上叠词和标题。转写后由你写 HyperFrames HTML，交给 media.hyperframes_caption 渲染。
---

# HyperFrames Captions

成片已经有了。你要做的是**在画面上叠字**：唱词、对白、标题、花字。

**你不是模板填充器。** 字长什么样由你写进 HTML。判断就是流程。

1. 对着**已经叠好音的成片**跑 `media.transcribe`。时间戳跟着成片走；用户没说翻译就保持原语言。
2. 自己看画面、歌、剧情。需要 `data-*` 合同时再 `video_skill_load("hyperframes-core")`。
3. **写出 caption HTML**（把 transcript 的词和时间写进去），交给 `media.hyperframes_caption` 的 `caption_html`。成片垫在底下。根跟着成片走，句跟着它唱的那几秒。GSAP 这份工程里已经有了。没有 `caption_html` 这次叠字就不会跑。
4. 同一条成片、同一份 transcript，一次叠完。

用户说不要字，这一步就停。静态硬烧另走 `video_skill_load("subtitle-authoring")`。

词跟着唱还是整句出、要不要标题、底栏还是花字——全由你定。用户点了样子就听用户的。同一位置一次看见一句。

中文必须能显示。字是给人读的，不要把主体挡到看不清。缺 Node / Chrome / GSAP / CLI 就把报错原样端上来。
