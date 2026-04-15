from app.services.inspection.source_cashflow_taxonomy import classify_cashflow_type


def test_classify_cashflow_type_maps_canonical_fee_and_external_flow():
    fee = classify_cashflow_type("fee")
    external = classify_cashflow_type("external_flow")

    assert fee.economics_role == "fee"
    assert fee.canonical is True
    assert fee.governed_alias is False
    assert external.economics_role == "external"
    assert external.canonical is True
    assert external.governed_alias is False


def test_classify_cashflow_type_maps_expense_as_fee_like_alias():
    classification = classify_cashflow_type(" EXPENSE ")

    assert classification.normalized_value == "expense"
    assert classification.economics_role == "fee"
    assert classification.canonical is False
    assert classification.governed_alias is True


def test_classify_cashflow_type_preserves_unsupported_income_taxonomy():
    classification = classify_cashflow_type("dividend")

    assert classification.economics_role == "unsupported"
    assert classification.canonical is False
    assert classification.governed_alias is False


def test_classify_cashflow_type_distinguishes_missing_labels():
    classification = classify_cashflow_type("   ")

    assert classification.normalized_value is None
    assert classification.economics_role == "missing"
    assert classification.canonical is False
    assert classification.governed_alias is False
