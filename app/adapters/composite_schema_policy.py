"""Shared canonical SQL constraints for tenant-owned composite metadata."""

PYTHON_STRIP_WHITESPACE_CODEPOINTS = (
    9,
    10,
    11,
    12,
    13,
    28,
    29,
    30,
    31,
    32,
    133,
    160,
    5760,
    8192,
    8193,
    8194,
    8195,
    8196,
    8197,
    8198,
    8199,
    8200,
    8201,
    8202,
    8232,
    8233,
    8239,
    8287,
    12288,
)
POSTGRES_STRIP_CHARACTERS_SQL = " || ".join(f"chr({codepoint})" for codepoint in PYTHON_STRIP_WHITESPACE_CODEPOINTS)
SQLITE_STRIP_CHARACTERS_SQL = " || ".join(f"char({codepoint})" for codepoint in PYTHON_STRIP_WHITESPACE_CODEPOINTS)
POSTGRES_TENANT_ID_CHECK_SQL = (
    "length(tenant_id) >= 1 AND length(tenant_id) <= 128 AND tenant_id = btrim(tenant_id, "
    + POSTGRES_STRIP_CHARACTERS_SQL
    + ")"
)
SQLITE_TENANT_ID_CHECK_SQL = (
    "length(tenant_id) BETWEEN 1 AND 128 AND tenant_id = trim(tenant_id, " + SQLITE_STRIP_CHARACTERS_SQL + ")"
)
CANONICAL_REPORTING_CURRENCY_CHECK_SQL = (
    "length(reporting_currency) = 3 "
    "AND reporting_currency = upper(reporting_currency) "
    "AND substr(reporting_currency, 1, 1) BETWEEN 'A' AND 'Z' "
    "AND substr(reporting_currency, 2, 1) BETWEEN 'A' AND 'Z' "
    "AND substr(reporting_currency, 3, 1) BETWEEN 'A' AND 'Z'"
)
SQLITE_POSITIVE_INTEGER_SEQUENCE_CHECK_SQL = "typeof(restatement_sequence) = 'integer' AND restatement_sequence >= 1"
SQLITE_PUBLICATION_DATE_CHECK_SQL = (
    "typeof(period_start) = 'text' "
    "AND length(period_start) = 10 "
    "AND period_start GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "
    "AND substr(period_start, 1, 4) BETWEEN '0001' AND '9999' "
    "AND julianday(period_start) IS NOT NULL "
    "AND date(julianday(period_start)) = period_start "
    "AND typeof(period_end) = 'text' "
    "AND length(period_end) = 10 "
    "AND period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "
    "AND substr(period_end, 1, 4) BETWEEN '0001' AND '9999' "
    "AND julianday(period_end) IS NOT NULL "
    "AND date(julianday(period_end)) = period_end"
)
