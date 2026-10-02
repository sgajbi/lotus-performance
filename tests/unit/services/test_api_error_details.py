from app.services.error_details import validation_error_envelope


def test_validation_error_envelope_never_echoes_request_inputs_or_context():
    envelope = validation_error_envelope(
        [
            {
                "type": "value_error",
                "loc": ("body", "weights"),
                "input": {"1": 0.25, "active": True, "missing": None},
                "ctx": {
                    "nested": (
                        {"bad": RuntimeError("unsupported weight")},
                        ["child", 2],
                    ),
                    42: "numeric key",
                },
            }
        ]
    )

    assert envelope["validation_errors"] == [
        {"type": "value_error", "loc": ["body", "weights"], "msg": "Request validation failed."}
    ]


def test_validation_error_envelope_bounds_diagnostics_without_echoing_inputs():
    errors = [
        {
            "type": "value_error",
            "loc": ("body", "positions_data", index),
            "msg": "x" * 500,
            "input": {"valuation_points": ["confidential"]},
        }
        for index in range(40)
    ]

    reported = validation_error_envelope(errors)["validation_errors"]

    assert len(reported) == 32
    assert len(reported[0]["msg"]) == 256
    assert reported[0]["loc"] == ["body", "positions_data", 0]
    assert "confidential" not in str(reported)
