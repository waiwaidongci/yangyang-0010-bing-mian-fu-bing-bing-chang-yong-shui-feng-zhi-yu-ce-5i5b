from fastapi import HTTPException


def crew(cx, code):
    row = cx.execute("SELECT * FROM resurfacing_crews WHERE code=%s FOR UPDATE", (code,)).fetchone()
    if row is None:
        raise HTTPException(404, "复冰机组不存在")
    return row


def allocations(cx):
    return cx.execute(
        """SELECT a.*,b.booking_ref,b.crew_label,r.rink_code,c.name AS crew_name,
                  (r.revision<>a.plan_revision) AS stale
           FROM crew_allocations a JOIN ice_bookings b ON b.id=a.booking_id
           JOIN water_shifts r ON r.id=b.shift_id JOIN resurfacing_crews c ON c.code=a.crew_code
           ORDER BY a.service_day,a.starts,a.id DESC LIMIT 80"""
    ).fetchall()


def crew_day(cx, code, day):
    return cx.execute(
        """SELECT starts,ends FROM crew_allocations WHERE crew_code=%s AND service_day=%s
           AND revoked_at IS NULL ORDER BY starts""", (code, day)
    ).fetchall()
