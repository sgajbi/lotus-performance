import pytest

from app.adapters.durable_schema.predicates import predicate_identity


@pytest.mark.parametrize(
    "source, catalog",
    [
        ("a >= 1 AND a <= 3", "((a >= 1) AND (a <= 3))"),
        ("a BETWEEN 1 AND 3", "a >= 1 AND a <= 3"),
        ("state IN ('READY', 'BLOCKED')", "state = ANY (ARRAY['READY'::text, 'BLOCKED'::text])"),
        (
            "state IN ('READY', 'BLOCKED')",
            "(state)::text = ANY ((ARRAY['READY'::character varying, 'BLOCKED'::character varying])::text[])",
        ),
        ("a = btrim(a, chr(9) || chr(10))", "a = btrim(a, (chr(9) || chr(10)))"),
        ("length(a) = 3", "(length((a)::text) = 3)"),
        ("a >= 1", "a::integer >= 1::bigint"),
        ("d >= '2026-01-01'", "d::date >= '2026-01-01'::date"),
        ("upper(a) = 'READY'", "upper(a)::text = 'READY'"),
    ],
)
def test_postgres_representation_differences_preserve_predicate(source, catalog):
    assert predicate_identity(
        source, text_columns={"a", "state"}, integer_columns={"a"}, date_columns={"d"}
    ) == predicate_identity(catalog, text_columns={"a", "state"}, integer_columns={"a"}, date_columns={"d"})


@pytest.mark.parametrize(
    "source, altered",
    [
        ("a AND (b OR c)", "(a AND b) OR c"),
        ("a >= 1 AND a <= 3", "a >= 1 OR a <= 3"),
        ("a = 'READY'", "a = 'ready'"),
        ("a >= 1", "a > 1"),
        ("a + b * c", "(a + b) * c"),
        ("a BETWEEN 1 AND 3", "a BETWEEN 1 AND 4"),
        ("a IN ('X', 'Y')", "a IN ('X', 'Y', 'Z')"),
        ("a = btrim(a, chr(9) || chr(10))", "a = btrim(a, chr(32))"),
        ("a IN ('X', 'Y')", "a NOT IN ('X', 'Y')"),
        ("a IS NULL", "a IS NOT NULL"),
        ("a BETWEEN 1 AND 3", "a NOT BETWEEN 1 AND 3"),
        ("a = 1", "-a = 1"),
        ("a = ANY(ARRAY[1, 2])", "a = ANY(ARRAY[1, 2]::text[])"),
        ("a > 2", "a::integer > 2"),
        ("a > 2", "a::date > 2"),
    ],
)
def test_material_predicate_changes_do_not_compare_equal(source, altered):
    assert predicate_identity(source, text_columns={"a"}) != predicate_identity(altered, text_columns={"a"})


def test_unapproved_cast_is_not_erased():
    assert predicate_identity("a > 2") != predicate_identity("a::text > '2'")


@pytest.mark.parametrize(
    "expression",
    ["CASE WHEN a THEN 1 ELSE 0 END = 1", "", "a NOT", "a = ?", "x " * 9000, "(" * 1500 + "a" + ")" * 1500],
)
def test_unsupported_expression_fails_closed(expression):
    with pytest.raises(ValueError, match="Unsupported durable check expression"):
        predicate_identity(expression)
