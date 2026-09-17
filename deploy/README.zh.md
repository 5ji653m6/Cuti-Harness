# 本地部署

[English](README.md) | 中文

自托管请用仓库根目录的 compose，这是支持的产品路径：

```sh
cp config/.env.example .env
docker compose --env-file .env -f deploy/compose.video.yml up --build -d
```

然后按[根目录 README](../README.zh.md) 启动 DeepSeek Harness。身份是 `local-user`。对象存储默认本地磁盘（`STORAGE_BACKEND=local`）。

| 端口 | 服务 |
|------|------|
| 3000 | Video Studio |
| 8001 | Video Runtime |
| 18080 | Media Service |

这条线只支持本地 compose。集群 Helm 和 overlay 留在私有分支。
