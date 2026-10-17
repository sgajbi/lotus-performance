"""Exact retained registration lookup; no source transport or signing material."""

from datetime import UTC, datetime

from app.adapters.composite_controlled_annual_configuration import decode_annual_configuration
from app.models.composite_authority import authority_digest


class ConfiguredControlledYearVerification:
    def __init__(self, configuration, *, now=None):
        self._wire = configuration.model_dump_json()
        self._now = now or (lambda: datetime.now(UTC))

    def configuration(self):
        value = decode_annual_configuration(self._wire)
        if not value.valid_from <= self._now() < value.valid_until:
            raise ValueError("Controlled annual deployment is outside its current validity interval.")
        return value

    def verify(self, request):
        try:
            configuration = self.configuration()
        except ValueError:
            return None
        digest = authority_digest(request.model_dump(mode="json"))
        if digest in configuration.revoked_request_digests:
            return None
        for row in configuration.registrations:
            if row.request_digest == digest and row.proof.request == request:
                return row.evidence()
        return None
