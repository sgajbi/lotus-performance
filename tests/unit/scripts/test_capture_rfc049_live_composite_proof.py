"""Operator credential transport controls; no live authority or financial proof."""

import base64
import json
import sys
from unittest.mock import Mock

import pytest

from scripts import capture_rfc049_live_composite_proof as proof


def _syntactic_credential():
    # Deliberately unsigned test bytes: only receiver-side authority can verify a grant.
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    return ".".join((encode(b'{"alg":"EdDSA"}'), encode(b'{"sub":"test-only"}'), encode(b"x" * 64)))


@pytest.mark.parametrize("credential", [None, "", "  ", "not-a-jws", "a.b.c", "Bearer a.b.c", "a.b.c\r\nInjected: yes"])
def test_invalid_operator_credential_refuses_before_http(monkeypatch, tmp_path, credential):
    send = Mock(side_effect=AssertionError("No HTTP before credential input admission"))
    monkeypatch.setattr(proof, "urlopen", send)
    with pytest.raises(ValueError, match="operator bearer credential"):
        proof.capture_live_proof(
            output_dir=tmp_path / "absent",
            performance_base_url="https://performance.test",
            gateway_base_url="https://gateway.test",
            workbench_base_url="https://workbench.test",
            bearer_token=credential,
        )
    send.assert_not_called()
    assert not (tmp_path / "absent").exists()


def test_cli_forwards_operator_credential_to_every_twr_probe_without_persisting_it(monkeypatch, tmp_path, capsys):
    credential = _syntactic_credential()
    monkeypatch.setenv("TEST_RFC049_OPERATOR_CREDENTIAL", credential)
    monkeypatch.setattr(
        sys, "argv", ["proof", "--bearer-token-env", "TEST_RFC049_OPERATOR_CREDENTIAL", "--output-dir", str(tmp_path)]
    )
    requests = []
    validators = []

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"source_service": "lotus-performance", "correlation_id": "test-correlation"}).encode()

    def send(request, **kwargs):
        requests.append(request)
        return Response()

    monkeypatch.setattr(proof, "urlopen", send)
    for name in ("_validate_ready_twr", "_validate_inspection", "_validate_degraded_twr", "_validate_no_facts"):

        def validate(result):
            validators.append(result.name)
            return [result.name]

        monkeypatch.setattr(proof, name, validate)
    proof.main()
    assert len(requests) == len(validators) == 8
    twr = [request for request in requests if request.full_url.endswith("/composites/twr")]
    assert len(twr) == 5
    assert all(request.get_header("Authorization") == "Bearer " + credential for request in twr)
    assert {request.full_url.split("/")[2] for request in twr} == {
        "performance.dev.lotus",
        "gateway.dev.lotus",
        "workbench.dev.lotus",
    }
    assert credential not in capsys.readouterr().out
    artifacts = list(tmp_path.glob("*.json"))
    assert len(artifacts) == 9
    assert all(credential not in path.read_text(encoding="utf-8") for path in artifacts)


@pytest.mark.parametrize("value", [None, "", "bad-token"])
def test_cli_absent_or_malformed_environment_value_has_safe_error(monkeypatch, tmp_path, capsys, value):
    if value is None:
        monkeypatch.delenv("TEST_RFC049_OPERATOR_CREDENTIAL", raising=False)
    else:
        monkeypatch.setenv("TEST_RFC049_OPERATOR_CREDENTIAL", value)
    monkeypatch.setattr(
        sys, "argv", ["proof", "--bearer-token-env", "TEST_RFC049_OPERATOR_CREDENTIAL", "--output-dir", str(tmp_path)]
    )
    send = Mock()
    monkeypatch.setattr(proof, "urlopen", send)
    with pytest.raises(SystemExit) as failure:
        proof.main()
    assert failure.value.code == 2
    send.assert_not_called()
    error = capsys.readouterr().err
    assert "operator bearer credential" in error
    assert "bad-token" not in error
