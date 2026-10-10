"""Fresh-process original replay with independent owners and no configured source."""

import json
import os
import sys
from uuid import UUID

from _pytest.monkeypatch import MonkeyPatch

from app.adapters.composite_attribution_deployment import (
    UnavailableAttributionSource,
    get_composite_attribution_deployment,
)
from app.adapters.composite_attribution_repository import read_attribution_input
from app.models.composite_attribution import CompositeAttributionResponse
from app.services.async_result_store import AsyncResultStore
from app.services.composite_attribution.application import job_principal
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.compute_job_store import ComputeJobStore
from tests.composite_authority_helpers import install_test_authorities


def main():
    url = os.environ["LOTUS_BF_REPLAY_DATABASE_URL"]
    calculation_id = UUID(sys.argv[1])
    retained_authorities = MonkeyPatch()
    with open(sys.argv[2], encoding="utf-8") as stream:
        install_test_authorities(retained_authorities, json.load(stream))
    owner, jobs, results = CompositeMetadataStore(url), ComputeJobStore(url), AsyncResultStore(url)
    try:
        owner.verify_schema()
        results.verify_schema()
        assert isinstance(get_composite_attribution_deployment().source, UnavailableAttributionSource)
        job = jobs.get_job(calculation_id)
        principal = job_principal(job)
        with owner._session() as session:
            snapshot = read_attribution_input(session.connection(), calculation_id, principal=principal)
        result = results.get_result_for_tenant(calculation_id, tenant_id=principal.tenant_id)
        response = CompositeAttributionResponse.model_validate(result.response_payload)
        assert snapshot.observation == response.observation
        print(
            json.dumps(
                {
                    "request": snapshot.request.model_dump(mode="json"),
                    "response": response.model_dump(mode="json"),
                    "source_deployment": "UNAVAILABLE",
                },
                sort_keys=True,
            )
        )
    finally:
        owner.close()
        jobs._engine.dispose()
        results._engine.dispose()
        retained_authorities.undo()


if __name__ == "__main__":
    main()
