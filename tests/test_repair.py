from rusted_recall.repair import (
    ERR_AUTH,
    ERR_RATE_LIMIT,
    build_repair_instruction,
    compute_idempotency_key,
    is_retryable,
)


def test_idempotency_key_is_stable():
    kwargs = dict(
        recall_event_id="r1",
        asset_version_id="v1",
        plan_version=1,
        provider="gmicloud",
        model="m",
        operation_parameters={"a": 1, "b": 2},
    )
    k1 = compute_idempotency_key(**kwargs)
    k2 = compute_idempotency_key(**kwargs)
    assert k1 == k2


def test_idempotency_key_order_independent_for_params():
    a = compute_idempotency_key(
        recall_event_id="r", asset_version_id="v", plan_version=1,
        provider="p", model="m", operation_parameters={"a": 1, "b": 2},
    )
    b = compute_idempotency_key(
        recall_event_id="r", asset_version_id="v", plan_version=1,
        provider="p", model="m", operation_parameters={"b": 2, "a": 1},
    )
    assert a == b


def test_idempotency_key_changes_with_inputs():
    base = dict(
        recall_event_id="r", asset_version_id="v", plan_version=1,
        provider="p", model="m", operation_parameters={"a": 1},
    )
    k = compute_idempotency_key(**base)
    base2 = dict(base)
    base2["asset_version_id"] = "v2"
    assert compute_idempotency_key(**base2) != k


def test_error_retry_classification():
    assert is_retryable(ERR_RATE_LIMIT)
    assert not is_retryable(ERR_AUTH)


def test_repair_instruction_is_asset_specific():
    i1 = build_repair_instruction(
        asset_type="hero_ad", asset_description="hero shot", old_reference="24-Hour Vitality",
        new_reference="Daily Botanical Blend", market="US",
    )
    i2 = build_repair_instruction(
        asset_type="web_banner", asset_description="wide banner", old_reference="24-Hour Vitality",
        new_reference="Daily Botanical Blend", market="US",
    )
    assert i1 != i2
    assert "24-Hour Vitality" in i1 and "Daily Botanical Blend" in i1
