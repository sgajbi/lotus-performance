"""One read dispatch for original member evidence, including component preflight."""

from app.adapters.composite_member_result_source import member_outcome
from app.adapters.composite_provider_member_source import AuthorityCompositeMemberResultSource


def read_member_evidence(command, reference, member_id, member_source, *, tenant_id, request_headers):
    arguments = dict(
        tenant_id=tenant_id, membership_snapshot_id=command.membership_content_hash, request_headers=request_headers
    )
    if isinstance(member_source, AuthorityCompositeMemberResultSource):
        return member_source.read_member(command, reference, member_id=member_id, **arguments)
    if reference is None:
        return member_outcome(member_id, code="MEMBER_CALCULATION_REFERENCE_REQUIRED")
    return member_source.read_member(command, reference, **arguments)
