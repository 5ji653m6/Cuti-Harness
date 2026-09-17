# workspace/ — workspace entity family

English | [中文](README.zh.md)

This family owns persistent workspaces: user directories with titles and ordered session membership.

| Package | Role | ctx key |
|---|---|---|
| [`workspace/`](workspace/README.md) | Registers workspaces and accounts for their sessions | `ctx.workspaceRegistry` |

The [workspace package reference](workspace/README.md) owns lifecycle, persistence, and deletion semantics.

The subsystem reference — the entity, realpath canon, registration/resolution — is [docs/subsystems/workspace.md](../../docs/subsystems/workspace.md); storage design in the [domain KV storage Agent Note](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/.agents/notes/proposed/architecture/2026-07-24-domain-kv-storage-and-workspace.md).
