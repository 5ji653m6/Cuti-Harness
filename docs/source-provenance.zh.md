# 源码来源

[English](source-provenance.md) | 中文

本仓库以 DeepSeek Harness 的源码与包历史为基础。导入基线是 DeepSeek Harness 提交 `b150a551`，`upstream` 指向 `https://github.com/deepseek-ai/deepseek-harness.git`。

Cuti Python 服务从提交 `39886e795685a5a88385ff2c3b68c4bbe7c7655a` 导入到 `services/video-runtime`，其已有 FFmpeg 微服务也从同一来源导入到 `services/media-service`。Cuti React 前端从提交 `aa6b08ae8c387917cef0b4a8d211c33cc5f84aa3` 导入到 `apps/video-studio`。

可发布源码不包含企业扩展目录和外部 Skill 集合。导入的兼容应用仍包含旧模块依赖的计费与运营引用，但独立 Video Runtime 不会安装或加载它们。支付、社区、运营、生成产物、日志、环境文件、密钥和第三方媒体仍属于发布排除类别；维护者发布兼容应用前必须完成逐文件许可证审核。

Cuti 源工作区包含本地修改。迁移过程单独审核了这些修改，只移植了适用于 Video Runtime 的 Provider 别名规范化与已启用 Workflow 的 Plan 校验变更。源仓库保持不变。

DeepSeek 文件保留原版权和 MIT 声明。新的 `@cuti-ai` 包与导入的 Cuti 代码采用本仓库 MIT 许可证。发布前必须重新生成 `THIRD_PARTY_NOTICES.md`，并核验每个分发的字体、模板、Skill、模型资产和媒体文件。
