from datetime import date

from fastapi import APIRouter, Depends

from core import db, require
from reconcile_models import MeterContrast, MeterVerdict
from reconcile_repository import reconcile_rows
from reconcile_service import adjudicate, compare

router = APIRouter(prefix="/api/registers")


@router.get("")
def sources(_=Depends(require())):
    with db() as cx:
        return {"registers": cx.execute("SELECT * FROM installed_registers ORDER BY code").fetchall(),
                "cases": reconcile_rows(cx)}


@router.post("/checks",status_code=201)
def submit(body: MeterContrast, _=Depends(require("operator"))):
    with db() as cx:
        return compare(cx, body)


@router.post("/checks/{code}/{day}/resolve")
def resolve(code: str, day: date, body: MeterVerdict, user=Depends(require("reviewer"))):
    with db() as cx:
        return adjudicate(cx, code, day, body, user["email"])
