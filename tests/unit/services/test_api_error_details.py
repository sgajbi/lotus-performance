from app.services.error_details import validation_error_envelope


def test_validation_error_envelope_preserves_json_scalars_and_nested_sequence_shape():
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
        {
            "type": "value_error",
            "loc": ["body", "weights"],
            "input": {"1": 0.25, "active": True, "missing": None},
            "ctx": {
                "nested": [
                    {"bad": "unsupported weight"},
                    ["child", 2],
                ],
                "42": "numeric key",
            },
        }
    ]
