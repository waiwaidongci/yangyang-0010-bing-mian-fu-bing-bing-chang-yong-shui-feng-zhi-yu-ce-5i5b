from fastapi import HTTPException


def find_register(cx, code):
    row = cx.execute("SELECT * FROM installed_registers WHERE code=%s", (code,)).fetchone()
    if row is None:
        raise HTTPException(404, "机械水表不存在")
    return row


def reconcile_rows(cx):
    return cx.execute(
        """SELECT c.*,m.passes,m.source_ticket,i.name AS rink_name
           FROM meter_variance_cases c JOIN resurfacing_meter m
             ON c.rink_code=m.rink_code AND c.metered_on=m.metered_on
           JOIN ice_rinks i ON i.code=c.rink_code
           ORDER BY c.metered_on DESC,c.rink_code LIMIT 80"""
    ).fetchall()
