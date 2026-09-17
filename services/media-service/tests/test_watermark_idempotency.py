from app.api.v1.pipeline import should_apply_watermark


def test_external_delivery_source_can_receive_one_watermark():
    assert should_apply_watermark(requested=True, source_is_first_party=False)


def test_first_party_artifact_never_receives_a_second_watermark():
    assert not should_apply_watermark(requested=True, source_is_first_party=True)


def test_canonical_pipeline_remains_clean_by_default():
    assert not should_apply_watermark(requested=False, source_is_first_party=False)


def test_delivery_copy_from_clean_canonical_can_force_one_overlay():
    assert should_apply_watermark(
        requested=True, source_is_first_party=True, force=True,
    )
