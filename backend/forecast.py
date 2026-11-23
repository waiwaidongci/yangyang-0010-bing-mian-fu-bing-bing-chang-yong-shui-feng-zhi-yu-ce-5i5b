from datetime import timedelta
from math import ceil
from statistics import mean

from fastapi import HTTPException
from psycopg.types.json import Jsonb

MIN_DAYS = 12
LOOKBACK = 21
HOLDOUT = 4
ALPHA = 0.65
BETA = 0.25


def holt(values, horizon):
    level, trend = values[0], values[1] - values[0]
    for observed in values[1:]:
        previous = level
        level = ALPHA * observed + (1 - ALPHA) * (level + trend)
        trend = BETA * (level - previous) + (1 - BETA) * trend
    return max(1.0, level + horizon * trend)


def validated_history(cx, rink, day):
    rows = cx.execute(
        """SELECT m.metered_on,m.passes,coalesce(c.effective_liters,m.volume_liters) AS volume_liters
           FROM resurfacing_meter m LEFT JOIN meter_variance_cases c
             ON c.rink_code=m.rink_code AND c.metered_on=m.metered_on
           WHERE m.rink_code=%s AND m.metered_on<%s ORDER BY m.metered_on DESC LIMIT %s""",
        (rink, day, LOOKBACK),
    ).fetchall()[::-1]
    if len(rows) < MIN_DAYS:
        raise HTTPException(409, "该冰面至少需要 12 个连续计量日")
    recent = rows[-MIN_DAYS:]
    if any(b["metered_on"] - a["metered_on"] != timedelta(days=1) for a, b in zip(recent, recent[1:])):
        raise HTTPException(409, "最近 12 个计量日存在缺口，请补齐水表记录")
    if (day - recent[-1]["metered_on"]).days > 3:
        raise HTTPException(409, "最近计量距计划日超过三天，请更新水表")
    start = len(rows) - MIN_DAYS
    while start > 0 and rows[start]["metered_on"] - rows[start - 1]["metered_on"] == timedelta(days=1):
        start -= 1
    return rows[start:]


def segment_plan(bookings, liters_per_pass):
    segments = []
    current = None
    for booking in bookings:
        if current is None or booking["refill_reason"]:
            current = {
                "start": booking["start_time"].isoformat(timespec="minutes"),
                "refill_reason": booking["refill_reason"],
                "liters": 0,
                "bookings": [],
            }
            segments.append(current)
        required = booking["passes"] * liters_per_pass
        current["liters"] += required
        current["bookings"].append({"ref": booking["booking_ref"], "passes": booking["passes"], "liters": required})
    return segments


def evaluate(cx, rink, shift, bookings, rows):
    values = [r["volume_liters"] / r["passes"] for r in rows]
    backtest = [
        {"date": rows[i]["metered_on"].isoformat(), "actual": values[i],
         "holt": holt(values[:i], 1), "last": values[i - 1]}
        for i in range(len(values) - HOLDOUT, len(values))
    ]
    errors = {model: mean(abs(row[model] - row["actual"]) for row in backtest) for model in ("holt", "last")}
    winner = "holt" if errors["holt"] < errors["last"] else "last"
    horizon = (shift["operating_day"] - rows[-1]["metered_on"]).days
    projection = holt(values, horizon) if winner == "holt" else values[-1]
    buffered = ceil(projection * (100 + rink["buffer_percent"]) / 100)
    segments = segment_plan(bookings, buffered)
    peak = max(segment["liters"] for segment in segments)
    within = peak <= rink["tank_liters"]
    result = cx.execute(
        """INSERT INTO water_forecasts
           (shift_id,plan_revision,meter_revision,model,projected_liters_per_pass,peak_segment_liters,
            within_capacity,backtest,segments)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,within_capacity,peak_segment_liters,model""",
        (shift["id"], shift["revision"], rink["meter_revision"], winner, buffered, peak, within,
         Jsonb({"raw_projection": projection, "horizon": horizon, "observations": len(values),
                "errors": errors, "holdout": backtest, "tank_liters": rink["tank_liters"],
                "buffer_percent": rink["buffer_percent"]}),
         Jsonb(segments)),
    ).fetchone()
    cx.execute(
        "UPDATE water_shifts SET status=%s WHERE id=%s", ("ready" if within else "blocked", shift["id"])
    )
    return result
