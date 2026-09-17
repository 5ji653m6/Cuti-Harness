# Local deploy

English | [中文](README.zh.md)

Self-host with the root compose file. That is the supported product path:

```sh
cp config/.env.example .env
docker compose --env-file .env -f deploy/compose.video.yml up --build -d
```

Then start DeepSeek Harness as described in the [root README](../README.md). Identity is `local-user`. Object storage defaults to the local disk (`STORAGE_BACKEND=local`).

| Port | Service |
|------|------|
| 3000 | Video Studio |
| 8001 | Video Runtime |
| 18080 | Media Service |

This track is local compose only. Cluster Helm and overlays stay on the private branch.
