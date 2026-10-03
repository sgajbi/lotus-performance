from decimal import Decimal
from typing import Annotated

from pydantic import WithJsonSchema

ExactDecimalInput = Annotated[
    Decimal,
    WithJsonSchema({"type": "number"}),
]
