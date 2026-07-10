from pydantic import BaseModel

from app.api.http_response_adapter import to_fastapi_response
from app.core.application_responses import accepted_application_response


class _AcceptedResponse(BaseModel):
    calculation_id: str
    recommended_poll_after_seconds: int


def test_accepted_application_response_projects_polling_guidance_header() -> None:
    response = accepted_application_response(
        _AcceptedResponse(calculation_id="calc-1", recommended_poll_after_seconds=3)
    )

    assert response.headers == {"Retry-After": "3"}

    fastapi_response = to_fastapi_response(response)

    assert fastapi_response.headers["retry-after"] == "3"
