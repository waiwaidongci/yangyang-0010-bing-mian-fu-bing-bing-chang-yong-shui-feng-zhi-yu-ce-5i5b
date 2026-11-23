from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


class SurveyDraft(BaseModel):
    ticket: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9-]{3,30}$")]
    rink_code: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9-]{3,30}$")]
    inspected_on: date
    retest_of: int | None = Field(default=None,ge=1)


class ZoneReading(BaseModel):
    zone: Literal["nw","nc","ne","sw","sc","se"]
    thickness_mm: Decimal = Field(ge=1,le=80,decimal_places=1)
    groove_mm: Decimal = Field(ge=0,le=20,decimal_places=1)
