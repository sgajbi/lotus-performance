"""Pure admission of dated synthetic ports, without allocating databases."""

import pytest

from tests.composite_authority_helpers import install_test_authorities
from tests.composite_authority_window_helpers import FEBRUARY, JANUARY, DatedMemberSource, window_command
from tests.composite_materialization_helpers import admitted


@pytest.mark.parametrize("window", [JANUARY, FEBRUARY])
@pytest.mark.parametrize("corrected", [False, True])
def test_dated_member_ports_bind_exact_monthly_request_assets_and_source(window, corrected, monkeypatch):
    command, packet = window_command(*window, corrected=corrected)
    install_test_authorities(monkeypatch, packet)
    products = [packet[key] for key in ("definition", "membership", "attestation")]
    source = admitted(command, products)
    assert source.attestation.coverage_to >= command.period_end
    port = DatedMemberSource(corrected=corrected)
    for reference in command.member_calculations:
        outcome = port.read_member(
            command,
            reference,
            tenant_id="tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={},
        )
        assert outcome.state == "READY"
        evidence = outcome.source_evidence
        assert evidence.calculation_request.portfolio.report_start_date == command.period_start
        assert evidence.calculation_request.portfolio.report_end_date == command.period_end
        assert evidence.source_assets.observations[0].valuation_date == command.period_start
        assert evidence.source_assets.observations[-1].valuation_date == command.period_end
        assert len(evidence.source_assets.observations) == (command.period_end - command.period_start).days + 1
