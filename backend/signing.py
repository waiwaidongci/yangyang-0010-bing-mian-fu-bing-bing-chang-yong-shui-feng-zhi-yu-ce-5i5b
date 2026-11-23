"""Signed-shift corrections: pause on a raised peak and release by supplement."""
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException

TZ = ZoneInfo("Asia/Shanghai")


def shift_started(shift):
    moment = datetime.combine(shift["operating_day"], shift["start_time"], tzinfo=TZ)
    return datetime.now(TZ) >= moment


def open_suspension(cx, shift_id):
    return cx.execute(
        """SELECT * FROM shift_suspensions
           WHERE shift_id=%s AND released_at IS NULL ORDER BY id DESC LIMIT 1""", (shift_id,)
    ).fetchone()


def check_recomputable(cx, rink, shift):
    """A signed shift may only be recomputed after its water tickets changed; a paused one may always."""
    if shift["status"] != "confirmed":
        return
    signed = cx.execute(
        "SELECT meter_revision FROM water_forecasts WHERE id=%s", (shift["confirmed_forecast"],)
    ).fetchone()
    if signed is not None and signed["meter_revision"] == rink["meter_revision"]:
        raise HTTPException(409, "班次已签署并锁定")


def suspend_if_raised(cx, rink, shift, forecast):
    """After a correction recompute, pause an unstarted signed shift when the signed peak rises."""
    if shift["status"] not in ("confirmed", "suspended") or shift_started(shift):
        return None
    signed = cx.execute(
        "SELECT * FROM water_forecasts WHERE id=%s", (shift["confirmed_forecast"],)
    ).fetchone()
    if signed is None or forecast["peak_segment_liters"] <= signed["peak_segment_liters"]:
        return None
    held = open_suspension(cx, shift["id"])
    if held is not None:
        # The same correction may be recomputed more than once; keep a single open suspension.
        cx.execute(
            """UPDATE shift_suspensions SET raising_forecast=%s,
                      raised_peak=GREATEST(raised_peak,%s) WHERE id=%s""",
            (forecast["id"], forecast["peak_segment_liters"], held["id"]),
        )
        return held
    reason = (f"水票更正后重算峰值 {forecast['peak_segment_liters']} L 高于原签报 "
              f"{signed['peak_segment_liters']} L，暂停执行，待复核补单")
    row = cx.execute(
        """INSERT INTO shift_suspensions
           (shift_id,cause,previous_forecast,previous_signed_by,previous_signed_at,
            raising_forecast,previous_peak,raised_peak,reason)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *""",
        (shift["id"], f"meter:{rink['meter_revision']}", signed["id"], shift["confirmed_by"],
         shift["confirmed_at"], forecast["id"], signed["peak_segment_liters"],
         forecast["peak_segment_liters"], reason),
    ).fetchone()
    if row is None:
        return open_suspension(cx, shift["id"])
    cx.execute(
        """UPDATE water_shifts SET status='suspended',suspended_at=now(),suspended_reason=%s
           WHERE id=%s""", (reason, shift["id"]),
    )
    return row


def _forecast_for(cx, shift, forecast_id):
    forecast = cx.execute(
        "SELECT * FROM water_forecasts WHERE id=%s AND shift_id=%s", (forecast_id, shift["id"])
    ).fetchone()
    if forecast is None:
        raise HTTPException(404, "补单引用的预测不属于该班次")
    return forecast


def require_latest(cx, rink, shift, forecast):
    latest = cx.execute(
        "SELECT id FROM water_forecasts WHERE shift_id=%s ORDER BY id DESC LIMIT 1", (shift["id"],)
    ).fetchone()
    if (latest is None or latest["id"] != forecast["id"]
            or forecast["plan_revision"] != shift["revision"]
            or forecast["meter_revision"] != rink["meter_revision"]):
        raise HTTPException(409, "水票或冰时已更新，请用最新水票重算补单")


def capacity_problem(forecast, rink):
    if not forecast["within_capacity"] or forecast["peak_segment_liters"] > rink["tank_liters"]:
        return (f"补单峰值 {forecast['peak_segment_liters']} L 超过水箱 "
                f"{rink['tank_liters']} L，请补排分段后重算")
    return None


def prepare(cx, rink, shift, forecast_id, note, actor):
    if shift["status"] != "suspended":
        raise HTTPException(409, "只有暂停执行的班次需要登记补单")
    if shift_started(shift):
        raise HTTPException(409, "班次已开工，不再以补单放行")
    held = open_suspension(cx, shift["id"])
    if held is None:
        raise HTTPException(409, "该班次没有待处理的停用记录")
    forecast = _forecast_for(cx, shift, forecast_id)
    require_latest(cx, rink, shift, forecast)
    pending = cx.execute(
        """SELECT 1 FROM supplement_orders WHERE suspension_id=%s AND status='prepared'""",
        (held["id"],),
    ).fetchone()
    if pending:
        raise HTTPException(409, "已有待签补单，请先由复核员签署")
    # The order records whatever was submitted; an over-capacity one is returned when signed.
    return cx.execute(
        """INSERT INTO supplement_orders
           (shift_id,suspension_id,forecast_id,forecast_plan_revision,forecast_meter_revision,
            peak_segment_liters,tank_liters,note,prepared_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (shift["id"], held["id"], forecast["id"], forecast["plan_revision"],
         forecast["meter_revision"], forecast["peak_segment_liters"], rink["tank_liters"],
         note, actor),
    ).fetchone()


def _return(cx, order_id, reason, actor):
    cx.execute(
        """UPDATE supplement_orders SET status='returned',returned_at=now(),returned_by=%s,
                  returned_reason=%s WHERE id=%s AND status='prepared'""",
        (actor, reason, order_id),
    )


def sign_supplement(cx, rink, shift, supplement_id, actor):
    order = cx.execute(
        "SELECT * FROM supplement_orders WHERE id=%s AND shift_id=%s", (supplement_id, shift["id"])
    ).fetchone()
    if order is None:
        raise HTTPException(404, "补单不存在")
    if order["status"] != "prepared":
        raise HTTPException(409, "该补单已签署或已退回")
    if shift["status"] != "suspended":
        raise HTTPException(409, "班次当前不在暂停状态")
    held = open_suspension(cx, shift["id"])
    if held is None or held["id"] != order["suspension_id"]:
        raise HTTPException(409, "停用记录已变化，请重新登记补单")
    forecast = _forecast_for(cx, shift, order["forecast_id"])
    try:
        require_latest(cx, rink, shift, forecast)
    except HTTPException as exc:
        _return(cx, order["id"], exc.detail, actor)
        return {"detail": exc.detail + "，补单已退回"}
    problem = capacity_problem(forecast, rink)
    if problem:
        _return(cx, order["id"], problem, actor)
        return {"detail": problem + "，补单已退回"}
    signed = cx.execute(
        """UPDATE supplement_orders SET status='signed',signed_by=%s,signed_at=now()
           WHERE id=%s AND status='prepared' RETURNING *""", (actor, order["id"]),
    ).fetchone()
    if signed is None:
        raise HTTPException(409, "该补单已处理")
    cx.execute(
        """UPDATE shift_suspensions SET released_at=now(),released_by=%s,supplement_id=%s
           WHERE id=%s""", (actor, signed["id"], held["id"]),
    )
    released = cx.execute(
        """UPDATE water_shifts SET status='confirmed',confirmed_forecast=%s,confirmed_by=%s,
                  confirmed_at=now(),suspended_at=NULL,suspended_reason=NULL
           WHERE id=%s RETURNING *""", (forecast["id"], actor, shift["id"]),
    ).fetchone()
    return {"shift": released, "supplement": signed}


def recompute_signed(cx, rink):
    """Recompute every unstarted signed shift on the rink after its water tickets changed."""
    from forecast import evaluate, validated_history
    from schedule import list_bookings

    shifts = cx.execute(
        "SELECT * FROM water_shifts WHERE rink_code=%s AND status IN ('confirmed','suspended') ORDER BY id",
        (rink["code"],),
    ).fetchall()
    results = []
    for shift in shifts:
        if shift_started(shift):
            continue
        try:
            slots = list_bookings(cx, shift["id"])
            history = validated_history(cx, rink["code"], shift["operating_day"])
            forecast = evaluate(cx, rink, shift, slots, history)
        except HTTPException as exc:
            results.append({"shift_id": shift["id"], "error": exc.detail})
            continue
        results.append({
            "shift_id": shift["id"],
            "forecast_id": forecast["id"],
            "peak_segment_liters": forecast["peak_segment_liters"],
            "suspended": open_suspension(cx, shift["id"]) is not None,
        })
    return results


def handover(cx, shift_id):
    shift = cx.execute(
        """SELECT s.*,r.name AS rink_name,r.tank_liters,r.meter_revision AS current_meter_revision
           FROM water_shifts s JOIN ice_rinks r ON r.code=s.rink_code WHERE s.id=%s""", (shift_id,)
    ).fetchone()
    if shift is None:
        raise HTTPException(404, "班次不存在")

    def forecast(forecast_id):
        if forecast_id is None:
            return None
        return cx.execute("SELECT * FROM water_forecasts WHERE id=%s", (forecast_id,)).fetchone()

    history = cx.execute(
        "SELECT * FROM shift_suspensions WHERE shift_id=%s ORDER BY id DESC", (shift_id,)
    ).fetchall()
    for item in history:
        item["previous"] = forecast(item["previous_forecast"])
        item["raising"] = forecast(item["raising_forecast"])
        item["supplements"] = cx.execute(
            "SELECT * FROM supplement_orders WHERE suspension_id=%s ORDER BY id DESC", (item["id"],)
        ).fetchall()
    latest = cx.execute(
        "SELECT * FROM water_forecasts WHERE shift_id=%s ORDER BY id DESC LIMIT 1", (shift_id,)
    ).fetchone()
    if shift["status"] in ("confirmed", "suspended"):
        shift["validation_state"] = shift["status"]
    elif latest is None:
        shift["validation_state"] = "draft"
    elif (latest["plan_revision"] != shift["revision"]
          or latest["meter_revision"] != shift["current_meter_revision"]):
        shift["validation_state"] = "stale"
    else:
        shift["validation_state"] = shift["status"]
    candidates = cx.execute(
        """SELECT * FROM water_forecasts WHERE shift_id=%s AND id>COALESCE(%s,0)
           ORDER BY id DESC LIMIT 8""", (shift_id, shift["confirmed_forecast"]),
    ).fetchall()
    suspended = shift["status"] == "suspended"
    signed = ({"by": shift["confirmed_by"], "at": shift["confirmed_at"],
               "forecast": forecast(shift["confirmed_forecast"])}
              if shift["confirmed_forecast"] else None)
    if signed is not None:
        signed["evidence_current"] = (
            signed["forecast"]["meter_revision"] == shift["current_meter_revision"])
    scheduling = cx.execute(
        """SELECT r.revision,b.id AS booking_id,b.booking_ref,b.crew_label,b.start_time,b.end_time,b.passes
           FROM water_shifts r JOIN ice_bookings b ON b.shift_id=r.id WHERE r.id=%s
           ORDER BY b.start_time,b.id""", (shift["id"],)
    ).fetchall()
    pending = None
    if suspended and candidates:
        candidate = candidates[0]
        pending = cx.execute(
            """SELECT * FROM supplement_orders WHERE shift_id=%s AND status='prepared'
               ORDER BY id DESC LIMIT 1""", (shift["id"],)
        ).fetchone()
    return {
        "shift": shift,
        "signed": signed,
        "latest": latest,
        "candidates": candidates,
        "scheduling": scheduling,
        "suspension": history[0] if suspended and history else None,
        "history": history,
        "pending_supplement": pending,
        "executable": signed["forecast"] if shift["status"] == "confirmed" else None,
    }
