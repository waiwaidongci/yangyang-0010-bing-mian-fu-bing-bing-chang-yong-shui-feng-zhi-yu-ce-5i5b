from fastapi import APIRouter, Depends, HTTPException

from core import db, require
from dispatch_models import CrewRequest
from dispatch_repository import allocations, crew
from dispatch_service import allocate

router = APIRouter(prefix="/api/crew-board")


@router.get("")
def board(_=Depends(require())):
    with db() as cx:
        return {"crews": cx.execute("SELECT * FROM resurfacing_crews ORDER BY code").fetchall(),
                "allocations": allocations(cx)}


@router.post("/allocations",status_code=201)
def assign(body: CrewRequest, user=Depends(require("operator"))):
    with db() as cx:
        return allocate(cx, body, user["email"])


@router.post("/allocations/{allocation_id}/revoke")
def void(allocation_id: int, _=Depends(require("operator"))):
    with db() as cx:
        row = cx.execute("SELECT crew_code FROM crew_allocations WHERE id=%s", (allocation_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "派车记录不存在")
        crew(cx, row["crew_code"])
        updated = cx.execute(
            "UPDATE crew_allocations SET revoked_at=now() WHERE id=%s AND revoked_at IS NULL RETURNING *",
            (allocation_id,),
        ).fetchone()
        if updated is None:
            raise HTTPException(409, "该派车已撤回")
        return updated
