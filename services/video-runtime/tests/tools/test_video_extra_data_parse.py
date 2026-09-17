"""
小测试：厘清 "Extra data: line 2 column 1" 的来源。

结论：
- 不是 wrapper 的 content_and_artifact 的 content 格式问题（model_dump_json() 只会出一段 JSON）。
- 更可能是 agent 最终输出（LLM 回复）里含多段 JSON 或 JSON 后带多余文本，被当作 VideoGenerationResult 解析时触发。

运行（需 conda env cuti-video-local）：
  cd Cuti-VideoAgent && python -m pytest tests/tools/test_video_extra_data_parse.py -v -s
"""
import json
import pytest


def test_video_result_model_dump_json_is_single_json():
    """Tool 返回的 content = result.model_dump_json() 应始终是单段 JSON，不会触发 Extra data。"""
    from app.models.image_result import VideoGenerationResult

    result = VideoGenerationResult(
        success=True,
        video_url="https://example.com/v.mp4",
        provider="wavespeed",
        duration=3.0,
        message="ok",
    )
    content = result.model_dump_json()
    assert isinstance(content, str)
    # 单段 JSON 必须能整段 parse，且不会有多余内容
    data = json.loads(content)
    assert data.get("success") is True
    assert data.get("video_url") == "https://example.com/v.mp4"
    # 若 content 后面再拼一段，就会 Extra data
    with pytest.raises(json.JSONDecodeError) as exc_info:
        json.loads(content + "\n" + '{"extra": true}')
    assert "Extra data" in str(exc_info.value)
    print("  [tool content] model_dump_json() 为单段 JSON ✓")
    print("  [tool content] 若后面再拼内容会触发 Extra data ✓")


def test_extra_data_comes_from_two_json_objects():
    """模拟：若某处把两段 JSON 拼成一段字符串再 parse，就会得到与线上一致的 Extra data。"""
    first = '{"success": true, "video_url": "https://a.com/1.mp4"}'
    second = '{"success": false, "message": "retry"}'
    combined = first + "\n" + second

    with pytest.raises(json.JSONDecodeError) as exc_info:
        json.loads(combined)
    assert "Extra data" in str(exc_info.value)
    # 通常报错会提到 line 2 column 1
    msg = str(exc_info.value).lower()
    assert "extra" in msg
    print("  [parse] 两段 JSON 拼在一起 -> Extra data ✓")
    print("  [parse] 错误信息:", str(exc_info.value)[:120])


def test_pydantic_validate_extra_data():
    """VideoGenerationResult.model_validate 对「多段 JSON 字符串」无法解析，需先取第一段。"""
    from app.models.image_result import VideoGenerationResult

    first = '{"success": true, "video_url": "https://a.com/1.mp4", "provider": "wavespeed"}'
    combined = first + "\n" + '{"extra": "second block"}'

    # 直接 parse 整段会失败（Pydantic 底层用 json.loads）
    with pytest.raises(Exception):
        VideoGenerationResult.model_validate_json(combined)
    print("  [pydantic] model_validate_json(combined) 会因 Extra data 失败 ✓")

    # 只取第一段 JSON 可正常解析
    data = json.loads(combined.split("\n")[0])
    parsed = VideoGenerationResult.model_validate(data)
    assert parsed.success is True
    assert parsed.video_url == "https://a.com/1.mp4"
    print("  [pydantic] 仅解析第一段 JSON 可得到合法 VideoGenerationResult ✓")
