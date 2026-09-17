"""媒体 URL 远端拉不到的错误应归为 invalid_input，不能被 "not allowed" 误判成内容审核。

回归点：WaveSpeed 对本地/私网 URL 返回
  "Invalid image URL: private or local network URLs are not allowed"
之前命中 _MODERATION_KEYWORDS 的 "not allowed" → 误报"内容未通过安全审核"。
"""
from app.utils.error_classification import (
    FailureCategory,
    classify_failure,
    user_facing_reason,
)


def test_wavespeed_private_local_url_classified_as_invalid_input():
    raw = (
        "Seedance 视频生成失败: 400, "
        '{"code":400,"message":"Invalid image URL: private or local network URLs are not allowed"}'
    )
    assert classify_failure(raw) == FailureCategory.INVALID_INPUT


def test_private_local_url_not_moderation_message():
    raw = "Invalid image URL: private or local network URLs are not allowed"
    msg = user_facing_reason(raw, lang="zh")
    # 不应出现"审核"字样（旧 bug 会返回"内容未通过安全审核"）
    assert "审核" not in msg


def test_download_failure_classified_as_invalid_input():
    for raw in [
        "failed to download image from url",
        "could not download the provided video",
        "unable to fetch audio url",
        "url is not accessible",
        "无法下载素材",
        "无法访问该地址",
    ]:
        assert classify_failure(raw) == FailureCategory.INVALID_INPUT, raw


def test_genuine_moderation_still_classified_as_moderation():
    """真正的审核类错误不受影响（守卫只拦媒体URL不可达）。"""
    for raw in [
        "content policy violation: nsfw detected",
        "request blocked by safety system",
        "内容违规，已拦截",
        "this prompt is not allowed by our content policy",
    ]:
        assert classify_failure(raw) == FailureCategory.CONTENT_MODERATION, raw


def test_provider_balance_not_regressed():
    """确保新守卫没误伤余额类（仍应是 service_unavailable）。"""
    raw = '{"code":400,"message":"Insufficient credits. Please top up your account to continue."}'
    assert classify_failure(raw) == FailureCategory.SERVICE_UNAVAILABLE
