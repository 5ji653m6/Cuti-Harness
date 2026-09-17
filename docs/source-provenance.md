# Source Provenance

English | [中文](source-provenance.zh.md)

This repository retains the DeepSeek Harness source and package history as its foundation. The imported baseline is DeepSeek Harness commit `b150a551`, and `upstream` points to `https://github.com/deepseek-ai/deepseek-harness.git`.

Cuti's Python service was imported from commit `39886e795685a5a88385ff2c3b68c4bbe7c7655a` into `services/video-runtime`. Its existing FFmpeg microservice was imported from the same source into `services/media-service`. Cuti's React frontend was imported from commit `aa6b08ae8c387917cef0b4a8d211c33cc5f84aa3` into `apps/video-studio`.

The distributable source excludes the enterprise extension tree and external Skill collection. The imported compatibility application still contains legacy billing and operations references required by old modules, but the standalone Video Runtime does not install or load them. Payment, community, operations, generated output, logs, environment files, secrets, and third-party media remain release-exclusion categories; maintainers must complete a file-level license review before publishing the compatibility application.

The source Cuti worktree contained local edits. Migration reviewed those edits separately and ported only the provider alias normalization and activated-workflow plan validation changes that apply to the Video Runtime. The source repositories remain unchanged.

DeepSeek files retain their original copyright and MIT notices. New `@cuti-ai` packages and imported Cuti code use the repository MIT license. A release must regenerate `THIRD_PARTY_NOTICES.md` and verify every distributed font, template, Skill, model asset, and media file.
