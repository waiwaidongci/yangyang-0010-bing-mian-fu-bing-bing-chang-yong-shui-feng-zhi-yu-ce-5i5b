from datetime import datetime, timedelta

from fastapi import HTTPException

from dispatch_repository import crew, crew_day
from inspection_repository import get_survey
from schedule import list_bookings, lock_shift

MINUTES_PER_PASS = 8


def find_gap(day, earliest, latest, duration, occupied):
    cursor = datetime.combine(day, earliest)
    deadline = datetime.combine(day, latest)
    for span in occupied:
        start = datetime.combine(day, span["starts"])
        end = datetime.combine(day, span["ends"])
        if start >= cursor + duration:
            break
        cursor = max(cursor, end)
    finish = cursor + duration
    if finish > deadline:
        raise HTTPException(409, "该机组没有足够的连续作业空档，需改派或调整冰时")
    return cursor.time(), finish.time()


def allocate(cx, body, actor):
    booking = cx.execute("SELECT shift_id FROM ice_bookings WHERE id=%s", (body.booking_id,)).fetchone()
    if booking is None:
        raise HTTPException(404, "冰时预约不存在")
    rink, shift = lock_shift(cx, booking["shift_id"])
    team = crew(cx, body.crew_code)
    survey = get_survey(cx, body.survey_id, lock=True)
    day = shift["operating_day"]
    latest = cx.execute(
        """SELECT id FROM ice_surveys WHERE rink_code=%s AND inspected_on<=%s
           ORDER BY inspected_on DESC,id DESC LIMIT 1""", (rink["code"], day)
    ).fetchone()
    if (survey["rink_code"] != rink["code"] or survey["status"] != "cleared" or latest is None
            or latest["id"] != survey["id"] or not 0 <= (day-survey["inspected_on"]).days <= 1):
        raise HTTPException(409, "派车须引用该冰面最近一天内且已放行的巡检")
    if rink["surface_m2"] > team["max_surface_m2"]:
        raise HTTPException(409, "该机组无法覆盖这块冰面的面积")
    slots = list_bookings(cx, shift["id"])
    idx = next(i for i,row in enumerate(slots) if row["id"] == body.booking_id)
    slot = slots[idx]
    earliest = max(team["works_from"], slots[idx-1]["end_time"] if idx else shift["start_time"])
    latest_end = min(team["works_until"],slot["start_time"])
    duration = timedelta(minutes=MINUTES_PER_PASS * slot["passes"] + (15 if slot["refill_reason"] else 0))
    starts, ends = find_gap(day, earliest, latest_end, duration, crew_day(cx, team["code"], day))
    row = cx.execute(
        """INSERT INTO crew_allocations(booking_id,crew_code,survey_id,plan_revision,service_day,starts,ends,allocated_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *""",
        (body.booking_id, team["code"], survey["id"], shift["revision"], day, starts, ends, actor),
    ).fetchone()
    if row is None:
        raise HTTPException(409, "该场次已有有效机组派车")
    return row
