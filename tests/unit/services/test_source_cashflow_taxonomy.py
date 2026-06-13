from app.services.source_cashflow_taxonomy import classify_cashflow_type


def test_classify_cashflow_type_maps_canonical_fee_and_external_flow():
    fee = classify_cashflow_type("fee")
    external = classify_cashflow_type("external_flow")
    transfer = classify_cashflow_type("transfer")

    assert fee.economics_role == "fee"
    assert fee.canonical is True
    assert fee.governed_alias is False
    assert external.economics_role == "external"
    assert external.canonical is True
    assert external.governed_alias is False
    assert transfer.economics_role == "external"
    assert transfer.canonical is True
    assert transfer.governed_alias is False


def test_classify_cashflow_type_maps_canonical_internal_trade_flow():
    classification = classify_cashflow_type("internal_trade_flow")

    assert classification.economics_role == "internal"
    assert classification.canonical is True
    assert classification.governed_alias is False


def test_classify_cashflow_type_maps_governed_fee_alias():
    classification = classify_cashflow_type(" MANAGEMENT_FEE ")

    assert classification.normalized_value == "management_fee"
    assert classification.economics_role == "fee"
    assert classification.canonical is False
    assert classification.governed_alias is True


def test_classify_cashflow_type_maps_governed_external_alias():
    classification = classify_cashflow_type(" TRANSFER_OUT ")

    assert classification.normalized_value == "transfer_out"
    assert classification.economics_role == "external"
    assert classification.canonical is False
    assert classification.governed_alias is True


def test_classify_cashflow_type_does_not_whitelist_expense_as_analytics_input_label():
    classification = classify_cashflow_type(" EXPENSE ")

    assert classification.normalized_value == "expense"
    assert classification.economics_role == "unsupported"
    assert classification.canonical is False
    assert classification.governed_alias is False


def test_classify_cashflow_type_preserves_unsupported_income_taxonomy():
    classification = classify_cashflow_type("dividend")

    assert classification.economics_role == "unsupported"
    assert classification.canonical is False
    assert classification.governed_alias is False


def test_classify_cashflow_type_distinguishes_missing_labels():
    classification = classify_cashflow_type("   ")
    non_string_classification = classify_cashflow_type(123)

    assert classification.normalized_value is None
    assert classification.economics_role == "missing"
    assert classification.canonical is False
    assert classification.governed_alias is False
    assert non_string_classification.normalized_value is None
    assert non_string_classification.economics_role == "missing"
    assert non_string_classification.canonical is False
    assert non_string_classification.governed_alias is False
