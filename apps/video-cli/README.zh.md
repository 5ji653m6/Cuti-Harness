# `@cuti-ai/video-agent-harness`

[English](README.md) | 中文

Cuti Video Harness 的本地启动器。它不依赖 Docker 即可启动 DeepSeek Harness、Python Video Runtime、Media Service、本地 Sandbox Worker 和 Video Studio。项目状态与生成媒体保存在同一个用户数据目录中。

```sh
npx @cuti-ai/video-agent-harness setup
npx @cuti-ai/video-agent-harness web
```

默认路径要求激活名为 `cuti-video-agent`、使用 Python 3.11 的 Conda 环境。请在准备前创建并激活它：

```sh
conda create --name cuti-video-agent python=3.11 pip
conda activate cuti-video-agent
```

`setup` 会验证这个具名环境，把固定版本的 Python 服务依赖安装进去，并在用户数据目录中安装采用单独许可证的 FFmpeg、FFprobe，以及固定版本的 HyperFrames 和 GSAP 渲染器。`web` 要求激活同一环境，只检查已经准备好的依赖并启动服务，不会下载 Python 或安装依赖。只有所选数据目录包含预期渲染器版本时，`doctor` 才会将 `Local HyperFrames renderer` 显示为 `OK`。

便携 Python 作为显式可选路径保留。先准备一次，并在启动时传入相同选项：

```sh
npx @cuti-ai/video-agent-harness setup --portable-python
npx @cuti-ai/video-agent-harness web --portable-python
```

不启动服务，仅运行诊断：

```sh
npx @cuti-ai/video-agent-harness doctor
```

如果环境准备阶段选择了便携 Python，诊断命令也需要传入 `--portable-python`。

## Known Limitations and Deferred Work

本地 Sandbox 作为普通子进程运行，不构成安全边界。执行不受信任的第三方插件时，请使用 Docker 部署。可选便携 Python 支持 Windows x64/arm64、macOS x64/arm64 和 glibc Linux x64/arm64；其他平台需要使用具名 Conda 环境。
