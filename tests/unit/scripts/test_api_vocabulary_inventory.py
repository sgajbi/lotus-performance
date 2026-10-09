import pytest

from scripts.api_vocabulary_inventory import _extract_fields, _fallback_example, _schema_type, build_inventory


def test_api_vocabulary_inventory_preserves_nullable_scalar_type():
    schema = {"anyOf": [{"type": "number"}, {"type": "null"}]}

    assert _schema_type(schema) == "number"
    assert _fallback_example("return_base", schema) == 0.1


@pytest.mark.parametrize("keyword", ["anyOf", "oneOf"])
def test_named_union_keeps_each_conditional_field_and_requiredness(keyword):
    components = {
        "schemas": {
            "Annual": {"type": "object", "properties": {"year": {"type": "integer"}}, "required": ["year"]},
            "Linked": {"type": "object", "properties": {"period_start": {"type": "string"}}},
        }
    }
    schema = {
        "discriminator": {"propertyName": "kind"},
        keyword: [
            {"$ref": "#/components/schemas/Annual"},
            {"$ref": "#/components/schemas/Linked"},
            {"type": "null"},
            None,
        ],
    }
    fields = _extract_fields(schema, components=components)
    assert [(field["name"], field["schemaVariant"], field["required"]) for field in fields] == [
        ("year", "Annual", True),
        ("period_start", "Linked", False),
    ]


def test_registered_analytics_inventory_preserves_annual_and_linked_variants():
    endpoint = next(
        item for item in build_inventory()["endpoints"] if item["path"] == "/performance/composites/analytics"
    )
    request = endpoint["request"]["fields"]
    assert any(
        field["name"] == "year" and field["schemaVariant"] == "CompositeAnnualDispersionRequest" for field in request
    )
    assert any(
        field["name"] == "period_start" and field["schemaVariant"] == "CompositeLinkedContributionRequest"
        for field in request
    )
    response = endpoint["response"]["fields"]
    assert any(
        field["name"] == "value" and field["schemaVariant"] == "CompositeAnnualDispersionResponse" for field in response
    )
    assert any(
        field["name"] == "members[].linked_contribution"
        and field["schemaVariant"] == "CompositeLinkedContributionResponse"
        for field in response
    )


@pytest.mark.parametrize("discriminator", [None, "kind", [], False])
def test_unnamed_or_malformed_union_is_not_expanded(discriminator):
    schema = {
        "anyOf": [{"$ref": "#/components/schemas/Annual"}, {"$ref": "#/components/schemas/Linked"}],
        "discriminator": discriminator,
    }
    components = {"schemas": {"Annual": {"properties": {"year": {"type": "integer"}}}}}
    assert _extract_fields(schema, components=components) == []
