"""Resolve only an exact configured local catalog binding; this grants no approval."""

from app.ports.composite_external_evidence import UnavailableCompositeEvidence


class RetainedCompositeModelFeeSource:
    def __init__(self, repository):
        self.repository = repository

    def resolve(self, request):
        receipt = self.repository.resolve_model_fee_profile(request)
        if receipt is None:
            return UnavailableCompositeEvidence()
        return receipt.profile.model_dump(mode="json")
