from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Evidence = Annotated[str,StringConstraints(strip_whitespace=True,min_length=4,max_length=120)]


class MeterContrast(BaseModel):
    register_code: str = Field(min_length=3,max_length=25)
    metered_on: date
    opening_mark: int = Field(ge=0,le=999999)
    closing_mark: int = Field(ge=0,le=999999)
    evidence: Evidence


class MeterVerdict(BaseModel):
    use_measured: bool
    resolution: Evidence
