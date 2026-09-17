# `@cuti-ai/video-agent-harness`

English | [中文](README.zh.md)

Local launcher for Cuti Video Harness. It starts DeepSeek Harness, the Python Video Runtime, Media Service, local Sandbox Worker, and Video Studio without Docker. Project state and generated media live under one user data directory.

```sh
npx @cuti-ai/video-agent-harness setup
npx @cuti-ai/video-agent-harness web
```

The default path requires an active Conda environment named `cuti-video-agent` with Python 3.11. Create and activate it before setup:

```sh
conda create --name cuti-video-agent python=3.11 pip
conda activate cuti-video-agent
```

`setup` verifies the named environment, installs the pinned Python service dependencies into it, and installs separately licensed FFmpeg and FFprobe tools plus the pinned HyperFrames and GSAP renderer in the user-data directory. `web` requires the same active environment and only verifies the prepared dependencies before starting services; it does not download Python or install dependencies. `doctor` reports `Local HyperFrames renderer` as `OK` only when the selected data directory contains the expected renderer versions.

Portable Python remains available as an explicit alternative. Prepare it once and pass the same option when starting:

```sh
npx @cuti-ai/video-agent-harness setup --portable-python
npx @cuti-ai/video-agent-harness web --portable-python
```

Run diagnostics without starting services:

```sh
npx @cuti-ai/video-agent-harness doctor
```

Pass `--portable-python` to diagnostics when that environment was selected during setup.

## Known Limitations and Deferred Work

Local Sandbox execution runs as an ordinary child process and is not a security boundary. Use the Docker deployment when executing untrusted third-party plugins. Optional portable Python supports Windows x64/arm64, macOS x64/arm64, and glibc Linux x64/arm64; other platforms require the named Conda environment.
