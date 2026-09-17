# Tests

## Runtime unit tests (no live providers)

```sh
python -m unittest discover -s tests/video_runtime -v
pytest tests/test_capability_architecture.py tests/test_v2_workflows.py tests/test_research_capability.py tests/test_host_gateway_and_bridge.py tests/test_mv_media_capabilities.py tests/test_atomic_direct.py tests/test_stage_skill_resolver.py -q
```

## Tool integration tests (`tests/tools/`)

These call real provider APIs and consume credits. Skip them with `pytest -m "not integration"`.

```sh
pytest tests/tools/test_suno_integration.py -v -s
pytest tests/tools/test_nano_banana_integration.py -v -s
```
