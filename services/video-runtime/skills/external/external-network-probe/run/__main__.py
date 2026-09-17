from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


input_path = Path(os.environ.get("CUTI_INPUT_JSON", "/workspace/input.json"))
output_dir = Path(os.environ.get("CUTI_OUTPUT_DIR", "/workspace/output"))
document = json.loads(input_path.read_text(encoding="utf-8"))
url = document.get("parameters", {}).get("url", "https://example.com")

with urllib.request.urlopen(url, timeout=15) as response:
    status = response.status

output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / "result.json").write_text(
    json.dumps(
        {
            "title": "External Skill execution succeeded",
            "summary": f"Python executed successfully; HTTP returned {status}.",
            "metadata": {
                "url": url,
                "http_status": status,
                "protocol_version": document.get("protocol_version"),
            },
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
