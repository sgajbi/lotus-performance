from scripts.api_vocabulary_inventory import _fallback_example, _schema_type


def test_api_vocabulary_inventory_preserves_nullable_scalar_type():
    schema = {"anyOf": [{"type": "number"}, {"type": "null"}]}

    assert _schema_type(schema) == "number"
    assert _fallback_example("return_base", schema) == 0.1
