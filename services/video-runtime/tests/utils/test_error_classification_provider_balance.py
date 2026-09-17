"""厂商账户余额类错误应归类为 service_unavailable 且脱敏后不泄露「充值/余额」。"""
from app.utils.error_classification import (
    FailureCategory,
    classify_failure,
    sanitize_user_facing_reason,
    user_facing_reason,
)


def test_provider_account_balance_classified_as_service_unavailable():
    raw = "账户余额不足，无法生成视频，请充值后重试。"
    assert classify_failure(raw) == FailureCategory.SERVICE_UNAVAILABLE


def test_provider_balance_sanitized_to_generic_message():
    raw = "账户余额不足，请充值后重试。"
    cat = classify_failure(raw)
    fallback = user_facing_reason(category=cat, lang="zh")
    out = sanitize_user_facing_reason(raw, fallback=fallback)
    assert "余额" not in out
    assert "充值" not in out
    assert "繁忙" in out or "稍后" in out


def test_wavespeed_insufficient_credits_classified_as_service_unavailable():
    """WaveSpeed 400 + Insufficient credits 不应误判为 invalid_input（内容不支持）。"""
    raw = (
        'Wan 2.6 视频生成失败: Wan 2.6 任务创建失败: 400, '
        '{"code":400,"message":"Insufficient credits. Please top up your account to continue."}'
    )
    assert classify_failure(raw) == FailureCategory.SERVICE_UNAVAILABLE
    msg = user_facing_reason(raw, lang="zh")
    assert msg == "生成服务暂时繁忙，请稍后重试。"
    assert "内容" not in msg
    assert "credit" not in msg.lower()


def test_wavespeed_insufficient_credits_sanitized_no_leak():
    raw = '{"code":400,"message":"Insufficient credits. Please top up your account to continue."}'
    cat = classify_failure(raw)
    fallback = user_facing_reason(category=cat, lang="zh")
    out = sanitize_user_facing_reason(raw, fallback=fallback)
    assert out == fallback
    assert "credit" not in out.lower()
    assert "top up" not in out.lower()
