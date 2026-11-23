from datetime import datetime, timedelta

from fastapi import HTTPException


def get_rink(cx, code, *, lock=False):
    row = cx.execute("SELECT * FROM ice_rinks WHERE code=%s" + (" FOR UPDATE" if lock else ""), (code,)).fetchone()
    if row is None:
        raise HTTPException(404, "冰面编号不存在")
    return row


def lock_shift(cx, shift_id):
    ref = cx.execute("SELECT rink_code FROM water_shifts WHERE id=%s", (shift_id,)).fetchone()
    if ref is None:
        raise HTTPException(404, "班次不存在")
    rink = get_rink(cx, ref["rink_code"], lock=True)
    shift = cx.execute("SELECT * FROM water_shifts WHERE id=%s FOR UPDATE", (shift_id,)).fetchone()
    return rink, shift


def list_bookings(cx, shift_id):
    return cx.execute(
        "SELECT * FROM ice_bookings WHERE shift_id=%s ORDER BY start_time,id", (shift_id,)
    ).fetchall()


def check_open_shift(shift):
    if shift["status"] == "confirmed":
        raise HTTPException(409, "班次已签署并锁定")


def touch_shift(cx, shift_id):
    cx.execute(
        "UPDATE water_shifts SET status='draft',revision=revision+1 WHERE id=%s", (shift_id,)
    )


def verify_itinerary(shift, rows):
    previous = None
    for slot in sorted(rows, key=lambda row: row["start_time"]):
        if not shift["start_time"] <= slot["start_time"] < slot["end_time"] <= shift["end_time"]:
            raise HTTPException(409, "冰时须在班次范围内，且结束晚于开始")
        if previous and slot["start_time"] < previous["end_time"]:
            raise HTTPException(409, "冰时重叠，无法同时复冰")
        if slot["refill_reason"]:
            if previous is None:
                raise HTTPException(409, "首场开始前水箱已满，无需额外补水")
            day = shift["operating_day"]
            gap = datetime.combine(day, slot["start_time"]) - datetime.combine(day, previous["end_time"])
            if gap < timedelta(minutes=15):
                raise HTTPException(409, "补水至少需要 15 分钟空档，请先调整冰时")
        previous = slot


def add_booking(cx, shift, body):
    check_open_shift(shift)
    bookings = list_bookings(cx, shift["id"])
    proposal = {**body.model_dump(), "refill_reason": None}
    verify_itinerary(shift, [*bookings, proposal])
    row = cx.execute(
        """INSERT INTO ice_bookings (shift_id,booking_ref,crew_label,start_time,end_time,passes)
           VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
        (shift["id"], body.booking_ref, body.crew_label, body.start_time, body.end_time, body.passes),
    ).fetchone()
    touch_shift(cx, shift["id"])
    return row


def revise_booking(cx, shift, booking_id, body):
    check_open_shift(shift)
    bookings = list_bookings(cx, shift["id"])
    slot = next((row for row in bookings if row["id"] == booking_id), None)
    if slot is None:
        raise HTTPException(404, "此班次没有该冰时")
    slot.update(body.model_dump())
    verify_itinerary(shift, bookings)
    updated = cx.execute(
        """UPDATE ice_bookings SET start_time=%s,end_time=%s,refill_reason=%s
           WHERE id=%s RETURNING *""",
        (slot["start_time"], slot["end_time"], slot["refill_reason"], booking_id),
    ).fetchone()
    touch_shift(cx, shift["id"])
    return updated


def confirm_shift(cx, rink, shift, forecast_id, actor):
    check_open_shift(shift)
    forecast = cx.execute(
        "SELECT * FROM water_forecasts WHERE shift_id=%s ORDER BY id DESC LIMIT 1", (shift["id"],)
    ).fetchone()
    if (forecast is None or forecast["id"] != forecast_id
            or forecast["plan_revision"] != shift["revision"] or forecast["meter_revision"] != rink["meter_revision"]):
        raise HTTPException(409, "冰时或计量已变更，请以新版本重算")
    if not forecast["within_capacity"]:
        raise HTTPException(409, "分段峰值超出水箱容量，请安排补水并重算")
    return cx.execute(
        """UPDATE water_shifts SET status='confirmed',confirmed_forecast=%s,confirmed_by=%s,confirmed_at=now()
           WHERE id=%s RETURNING *""", (forecast_id, actor, shift["id"])
    ).fetchone()
