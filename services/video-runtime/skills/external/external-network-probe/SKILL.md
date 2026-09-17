---
name: external-network-probe
description: Verify that an external development skill can execute Python and access HTTP.
---

# External Network Probe

Development-only capability used to verify the external Skill Bundle execution path.

```cuti-contract
{
  "contract_version": 1,
  "capability_id": "external.network.probe",
  "executor": "sandbox.run",
  "target": "run/__main__.py",
  "produces": "json",
  "parameters_schema": {
    "type": "object",
    "properties": {
      "url": {"type": "string"}
    },
    "additionalProperties": false
  },
  "output_schema": {
    "type": "object",
    "required": ["title", "summary", "metadata"],
    "properties": {
      "title": {"type": "string"},
      "summary": {"type": "string"},
      "metadata": {"type": "object"}
    },
    "additionalProperties": true
  },
  "sandbox": {
    "entrypoint": "run/__main__.py",
    "network": "allowlist",
    "allowed_domains": ["example.com"],
    "allowed_host_capabilities": ["artifact.read", "artifact.write", "log", "progress", "http.fetch"]
  }
}
```
