# External Skill authoring (hot-load)

## Platform policy (mandatory)

**Do not modify third-party Skill contents** (e.g. `seedance2`) to fit Cuti.
Unless the user explicitly requests a Skill edit, only change platform/host logic
(host gateway, provider bridge, sandbox env, coordinator). Skills stay
upstream-compatible so install/reload is true hot update.

## Instruction-only vs executable

| Kind | Contract | Creates capability? | Use when |
|------|----------|---------------------|----------|
| Instruction-only | none | no | Creative workflows that **compose** existing capabilities or run bundled scripts |
| Executable | `executor: sandbox.run` | yes (on install/reload) | Vendor logic / scripts that must hot-load **as authored by the Skill author** |

External Skills **must** use `sandbox.run` if they ship an executable contract. Trusted `.system` Skills may use `local.service`.

Upstream instruction-only Skills (like stock `seedance2` calling `scripts/seedance.py` + Ark) must keep working via **platform interception** (env keys, host bridge, script runner), not by rewriting their `SKILL.md`.

## Host capabilities (generic)

Sandbox Skills call the Agent host gateway (injected as `_cuti_host.host_dispatch`):

- `provider.generate` — normalized video generate; Ark if `ARK_API_KEY`, else WaveSpeed via `DEEP_AGENT_V2_PROVIDER_FALLBACKS_JSON`
- `media.concat` — ordered `video_urls[]` → MP4 (audio preserved)
- `media.extract_frame` — `video_url` + `timestamp` (seconds) → still image
- `api.ark_protocol.generate` — Ark Seedance wire body → WaveSpeed → Ark-shaped status (`content.video_url`); Skill: `ark-wavespeed-protocol-bridge`
- `http.request` / `http.fetch` — allowlisted public hosts only
- `artifact.read` / `artifact.write` / `log` / `progress`

### Ark protocol bridge (seedance2 unchanged)

When `scripts/seedance.py` runs without a real `ARK_API_KEY` but with `WAVESPEED_API_KEY`, the sandbox injects `sitecustomize` so `ark.cn-beijing.volces.com` HTTP is rewritten to the host Ark-compatible endpoints under `/internal/host/ark/api/v3/...`. WaveSpeed runs underneath; responses stay Ark-shaped for the upstream CLI. Toggle: `DEEP_AGENT_V2_ARK_PROTOCOL_BRIDGE`.

Do **not** ask the platform team to add `if skill_name == "..."` branches. Put vendor details in the Skill bundle (author-owned) or upgrade the provider-bridge mapping config.

## Contract sketch

```json
{
  "capability_id": "my.skill",
  "executor": "sandbox.run",
  "target": "run/__main__.py",
  "produces": "video",
  "sandbox": {
    "entrypoint": "run/__main__.py",
    "network": "allowlist",
    "allowed_domains": ["api.example.com"],
    "allowed_host_capabilities": [
      "provider.generate",
      "media.concat",
      "media.extract_frame",
      "http.request",
      "artifact.write"
    ],
    "timeout_seconds": 900
  }
}
```

## Install

`POST /chat-v1/service/v2/internal/skills/install-archive` with the zip, then reload.
Coordinator will see the capability via `list_capabilities` without Agent code changes.
