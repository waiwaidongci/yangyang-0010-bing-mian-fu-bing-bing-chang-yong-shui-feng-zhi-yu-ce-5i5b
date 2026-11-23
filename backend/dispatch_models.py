from pydantic import BaseModel, Field


class CrewRequest(BaseModel):
    booking_id: int = Field(ge=1)
    crew_code: str = Field(min_length=3,max_length=24)
    survey_id: int = Field(ge=1)
