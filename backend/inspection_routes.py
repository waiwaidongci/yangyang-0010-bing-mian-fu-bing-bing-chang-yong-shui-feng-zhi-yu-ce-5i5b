from fastapi import APIRouter, Depends

from core import db, require
from inspection_models import SurveyDraft, ZoneReading
from inspection_repository import survey_map
from inspection_service import create, observe, sign

router = APIRouter(prefix="/api/surveys")


@router.get("")
def surveys(_=Depends(require())):
    with db() as cx:
        return survey_map(cx)


@router.post("",status_code=201)
def start(body: SurveyDraft, _=Depends(require("operator"))):
    with db() as cx:
        return create(cx, body)


@router.put("/{survey_id}/zones")
def sample(survey_id: int, body: ZoneReading, _=Depends(require("operator"))):
    with db() as cx:
        return observe(cx, survey_id, body)


@router.post("/{survey_id}/sign")
def review(survey_id: int, user=Depends(require("reviewer"))):
    with db() as cx:
        return sign(cx, survey_id, user["email"])
