"""Independent monetary cancellation controls in both numerical return modes."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from common.enums import PeriodType
from engine.attribution import _base_weight_record_from_point
from engine.compute import _use_exact_integer_monetary_workspace, run_calculations
from engine.config import EndingValueBasis, EngineConfig, PrecisionMode
from engine.monetary_weights import add_monetary_series, calculate_monetary_weights
from engine.numerical_boundary import NumericalDomainError, monetary_arithmetic_context


@pytest.mark.parametrize("basis", ["NET", "GROSS"])
@pytest.mark.parametrize("ending_basis", list(EndingValueBasis))
@pytest.mark.parametrize("flow", ["0", "9007199254740993", "1152921504606846976", "0.01"])
def test_integer_workspace_and_decimal_fallback_preserve_independent_profit(basis, ending_basis, flow):
    from decimal import localcontext

    with localcontext() as context:
        context.prec = 60
        fee = Decimal("-1.00")
        closing = Decimal("110.00") + Decimal(flow)
        # Before-fee input excludes booked fees; after-fee input includes them.
        if ending_basis == EndingValueBasis.AFTER_FEES:
            closing += fee
    source = pd.DataFrame(
        [
            {
                "perf_date": date(2025, 1, 1),
                "begin_mv": Decimal("100.00"),
                "end_mv": closing,
                "bod_cf": Decimal("0.00"),
                "eod_cf": Decimal(flow),
                "mgmt_fees": fee,
            }
        ]
    )
    original = source.copy(deep=True)
    results = []
    for mode in PrecisionMode:
        config = EngineConfig(
            performance_start_date=date(2025, 1, 1),
            report_end_date=date(2025, 1, 1),
            period_type=PeriodType.SI,
            metric_basis=basis,
            precision_mode=mode,
            ending_value_basis=ending_basis,
        )
        result, _ = run_calculations(source, config)
        results.append(result)
        assert float(result.iloc[0]["daily_ror"]) == pytest.approx(9 if basis == "NET" else 10)
        for column in ["begin_mv", "bod_cf", "eod_cf", "mgmt_fees", "end_mv"]:
            assert isinstance(result.iloc[0][column], Decimal)
    pd.testing.assert_frame_equal(source, original)
    for column in ["sign", "nip", "nip_rule_v1_shadow", "nip_rule_v2_shadow", "perf_reset"]:
        assert results[0][column].tolist() == results[1][column].tolist()


@pytest.mark.parametrize("reverse", [False, True])
def test_precision_scan_deduplication_preserves_equivalent_representations_and_carry(reverse):
    amounts = [Decimal("100.0000"), Decimal("1E+2"), Decimal("-99.9999")]
    if reverse:
        amounts.reverse()
    with monetary_arithmetic_context(amounts * 10000, products=True):
        assert sum(amounts) == Decimal("100.0001")
        assert sum(amounts * 10000) == Decimal("1000001.0000")


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_precision_scan_refuses_nonfinite_before_deduplication(value):
    with pytest.raises(NumericalDomainError, match="finite"):
        with monetary_arithmetic_context([Decimal(value)]):
            pytest.fail("Nonfinite amount reached arithmetic")


@pytest.mark.parametrize("amount", [Decimal("0E-5000"), Decimal("1." + "0" * 5000)])
def test_precision_scan_does_not_hide_out_of_domain_equivalent_representation(amount):
    ordinary = Decimal(0) if amount == 0 else Decimal(1)
    with pytest.raises(NumericalDomainError, match="bounded"):
        with monetary_arithmetic_context([ordinary, amount]):
            pytest.fail("Deduplication hid an out-of-domain representation")


@pytest.mark.parametrize("amount", ["1152921504606846975", "-1152921504606846975", "100.00"])
def test_exact_integer_workspace_accepts_bounded_whole_amount_and_retains_representation(amount):
    frame = pd.DataFrame({name: [Decimal(amount)] for name in ["begin_mv", "bod_cf", "eod_cf", "mgmt_fees", "end_mv"]})
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.SI,
    )
    retained = _use_exact_integer_monetary_workspace(frame, config)
    assert len(retained) == 5
    for column in retained:
        assert frame[column].dtype == "int64"
        assert int(frame[column].iloc[0]) == int(Decimal(amount))
        assert str(retained[column].iloc[0]) == amount


@pytest.mark.parametrize("amount", ["1152921504606846976", "-1152921504606846976", "0.01"])
def test_exact_integer_workspace_falls_back_without_mutating_amounts(amount):
    frame = pd.DataFrame({name: [Decimal(amount)] for name in ["begin_mv", "bod_cf", "eod_cf", "mgmt_fees", "end_mv"]})
    original = frame.copy(deep=True)
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.SI,
    )
    assert _use_exact_integer_monetary_workspace(frame, config) == {}
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("mode", list(PrecisionMode))
@pytest.mark.parametrize(
    ("end", "flow", "fees", "expected"),
    [
        ("9007199254741093.02", "9007199254740993.01", "0", "0.01"),
        ("9007199254741093.01", "9007199254740993.01", "0", "0"),
        ("9007199254741093.00", "9007199254740993.01", "0", "-0.01"),
        ("9007199254741093.02", "9007199254740993.01", "-0.01", "0"),
        ("9007199254740993000000000000000100.02", "9007199254740993000000000000000000.01", "0", "0.01"),
    ],
)
def test_large_end_day_deposit_does_not_destroy_cent_economics(mode, end, flow, fees, expected):
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        period_type=PeriodType.SI,
        metric_basis="NET",
        precision_mode=mode,
    )
    source = pd.DataFrame(
        [
            {
                "perf_date": date(2025, 1, 1),
                "begin_mv": Decimal("100"),
                "end_mv": Decimal(end),
                "eod_cf": Decimal(flow),
                "bod_cf": Decimal(0),
                "mgmt_fees": Decimal(fees),
            }
        ]
    )
    result, _ = run_calculations(source, config)
    assert float(result.iloc[0]["daily_ror"]) == pytest.approx(float(expected), abs=1e-12)
    assert result.iloc[0]["end_mv"] == Decimal(end)
    assert result.iloc[0]["eod_cf"] == Decimal(flow)
    if mode == PrecisionMode.FLOAT64:
        assert isinstance(result.iloc[0]["daily_ror"], float)
    else:
        assert isinstance(result.iloc[0]["daily_ror"], Decimal)
        assert result.iloc[0]["daily_ror"] == Decimal(expected)


@pytest.mark.parametrize("decimal_mode", [True, False])
def test_monetary_weights_preserve_signed_cent_profit_and_date_alignment(decimal_mode):
    amounts = pd.Series([Decimal("0.01"), Decimal("-0.02")], index=["first", "second"])
    capitals = pd.Series([Decimal("200"), Decimal("100")], index=["second", "first"])
    weights = calculate_monetary_weights(amounts, capitals, decimal_mode=decimal_mode)
    expected = [Decimal("0.0001"), Decimal("-0.0001")]
    assert list(weights.index) == ["first", "second"]
    if decimal_mode:
        assert weights.tolist() == expected
    else:
        assert weights.tolist() == [float(value) for value in expected]


def test_monetary_weight_float64_refuses_unrepresentable_ratio():
    with pytest.raises(NumericalDomainError):
        calculate_monetary_weights(pd.Series([Decimal("1e400")]), pd.Series([Decimal(1)]), decimal_mode=False)


def test_capital_addition_retains_cent_beside_large_balance():
    capital = add_monetary_series(
        pd.Series([Decimal("9007199254740993000000000000000000")]), pd.Series([Decimal("0.01")])
    )
    assert capital.iloc[0] == Decimal("9007199254740993000000000000000000.01")


@pytest.mark.parametrize("mode", list(PrecisionMode))
def test_engine_refuses_unrepresentable_percentage_without_fx(mode):
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        period_type=PeriodType.SI,
        metric_basis="GROSS",
        precision_mode=mode,
    )
    source = pd.DataFrame([{"perf_date": date(2025, 1, 1), "begin_mv": Decimal("100"), "end_mv": Decimal("1e400")}])
    with pytest.raises(NumericalDomainError):
        run_calculations(source, config)


def test_source_base_weight_capital_retains_signed_cent_cancellation():
    record = _base_weight_record_from_point(
        {"perf_date": "2025-01-01", "begin_mv": "9007199254740993.01", "bod_cf": "-9007199254740993.00"}
    )
    assert record is not None
    assert record["capital"] == Decimal("0.01")
