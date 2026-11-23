from datetime import date, datetime, time
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from core import db, enqueue, require
from forecast import evaluate, validated_history
from schedule import add_booking, check_open_shift, confirm_shift, get_rink, list_bookings, lock_shift, revise_booking

router = APIRouter(prefix="/api")
Read = Depends(require())
Operator = Depends(require("operator"))
Reviewer = Depends(require("reviewer"))
Analyst = Depends(require("operator", "reviewer"))
Ticket = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z0-9-]{3,24}$")]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]


class MeterEntry(BaseModel):
    metered_on: date
    passes: int = Field(ge=1, le=24)
    volume_liters: int = Field(ge=20, le=24000)
    source_ticket: Ticket

    @model_validator(mode="after")
    def check_total(self):
        if not 20 * self.passes <= self.volume_liters <= 1000 * self.passes:
            raise ValueError("单次平均用水须在 20 到 1000 升之间")
        if self.metered_on > datetime.now(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("计量日期不能在将来")
        return self


class BookingTimes(BaseModel):
    start_time: time
    end_time: time

    @field_validator("start_time", "end_time")
    @classmethod
    def local_minute(cls, value):
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("冰时请填北京时间的本地时分")
        return value


class Booking(BookingTimes):
    booking_ref: Ticket
    crew_label: Description
    passes: int = Field(ge=1, le=4)


class Revision(BookingTimes):
    refill_reason: Description | None = None


class Confirmation(BaseModel):
    forecast_id: int = Field(ge=1)


@router.get("/rinks")
def rinks(_=Read):
    with db() as cx:
        return cx.execute("SELECT * FROM ice_rinks ORDER BY code").fetchall()


@router.get("/rinks/{code}/meter")
def meters(code: str, _=Read):
    with db() as cx:
        get_rink(cx, code)
        return cx.execute(
            """SELECT *, round(volume_liters::numeric / passes, 1) AS liters_per_pass FROM resurfacing_meter
               WHERE rink_code=%s ORDER BY metered_on DESC LIMIT 30""", (code,)
        ).fetchall()


@router.post("/rinks/{code}/meter", status_code=201)
def meter(code: str, body: MeterEntry, _=Operator):
    with db() as cx:
        get_rink(cx, code, lock=True)
        new = cx.execute(
            """INSERT INTO resurfacing_meter (rink_code,metered_on,passes,volume_liters,source_ticket)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *""",
            (code, body.metered_on, body.passes, body.volume_liters, body.source_ticket),
        ).fetchone()
        if new is None:
            raise HTTPException(409, "该日或计量票据已登记")
        cx.execute("UPDATE ice_rinks SET meter_revision=meter_revision+1 WHERE code=%s", (code,))
        return new


@router.get("/shifts")
def shifts(_=Read):
    with db() as cx:
        return cx.execute(
            """SELECT s.*, r.name AS rink_name, r.tank_liters, latest.id AS latest_forecast,
                      latest.peak_segment_liters, latest.within_capacity,
                      CASE
                        WHEN s.status='confirmed' THEN 'confirmed'
                        WHEN latest.id IS NULL THEN 'draft'
                        WHEN latest.plan_revision<>s.revision OR latest.meter_revision<>r.meter_revision THEN 'stale'
                        ELSE s.status
                      END AS validation_state
               FROM water_shifts s JOIN ice_rinks r ON r.code=s.rink_code
               LEFT JOIN LATERAL (
                   SELECT * FROM water_forecasts w WHERE w.shift_id=s.id ORDER BY w.id DESC LIMIT 1
               ) latest ON TRUE ORDER BY s.operating_day,s.start_time,s.rink_code"""
        ).fetchall()


@router.get("/shifts/{shift_id}/bookings")
def bookings(shift_id: int, _=Read):
    with db() as cx:
        if not cx.execute("SELECT 1 FROM water_shifts WHERE id=%s", (shift_id,)).fetchone():
            raise HTTPException(404, "班次不存在")
        return list_bookings(cx, shift_id)


@router.post("/shifts/{shift_id}/bookings", status_code=201)
def book(shift_id: int, body: Booking, _=Operator):
    with db() as cx:
        _, shift = lock_shift(cx, shift_id)
        return add_booking(cx, shift, body)


@router.put("/shifts/{shift_id}/bookings/{booking_id}")
def revise(shift_id: int, booking_id: int, body: Revision, _=Operator):
    with db() as cx:
        _, shift = lock_shift(cx, shift_id)
        return revise_booking(cx, shift, booking_id, body)


@router.get("/shifts/{shift_id}/forecasts")
def forecasts(shift_id: int, _=Read):
    with db() as cx:
        return cx.execute(
            "SELECT * FROM water_forecasts WHERE shift_id=%s ORDER BY id DESC LIMIT 8", (shift_id,)
        ).fetchall()


def check_inputs(cx, rink, shift):
    check_open_shift(shift)
    slots = list_bookings(cx, shift["id"])
    if not slots:
        raise HTTPException(409, "请先排定至少一个复冰预约")
    return slots, validated_history(cx, rink["code"], shift["operating_day"])


@router.post("/shifts/{shift_id}/forecasts", status_code=202)
def queue(shift_id: int, _=Analyst):
    with db() as cx:
        rink, shift = lock_shift(cx, shift_id)
        check_inputs(cx, rink, shift)
        return {"job_id": enqueue(cx, "forecast", {
            "shift_id": shift_id, "plan_revision": shift["revision"], "meter_revision": rink["meter_revision"],
        })}


@router.post("/shifts/{shift_id}/confirm")
def confirm(shift_id: int, body: Confirmation, actor=Reviewer):
    with db() as cx:
        rink, shift = lock_shift(cx, shift_id)
        return confirm_shift(cx, rink, shift, body.forecast_id, actor["email"])


def run_job(cx, kind, payload):
    if kind != "forecast":
        raise ValueError(f"Unknown job: {kind}")
    rink, shift = lock_shift(cx, payload["shift_id"])
    if shift["revision"] != payload["plan_revision"] or rink["meter_revision"] != payload["meter_revision"]:
        raise HTTPException(409, "冰时或计量已变更，请重新提交预测")
    slots, history = check_inputs(cx, rink, shift)
    return evaluate(cx, rink, shift, slots, history)


def seed(cx):
    from rink_seed import seed_ice_rinks
    seed_ice_rinks(cx)
