from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer, WithJsonSchema

ExactDecimalInput = Annotated[
    Decimal,
    WithJsonSchema({"type": "number"}),
]

MonetaryJSONNumber = Annotated[
    Decimal,
    PlainSerializer(lambda value: float(value), return_type=float),  # monetary-float-allow: JSON number compatibility
]
