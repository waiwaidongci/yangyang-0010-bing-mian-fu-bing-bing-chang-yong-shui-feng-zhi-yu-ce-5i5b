from fastapi import HTTPException

from reconcile_repository import find_register
from schedule import get_rink
from signing import recompute_signed


def register_delta(opening, closing, cycle):
    if not 0 <= opening < cycle or not 0 <= closing < cycle:
        raise HTTPException(409, "表码须小于机械刻度回零值")
    if closing > opening:
        return closing - opening, False
    if closing < opening and 5 * opening >= 4 * cycle and 5 * closing <= cycle:
        return cycle - opening + closing, True
    raise HTTPException(409, "回零记录须从表盘末段跨到起始段，其他倒退需核查表号")


def compare(cx, body):
    register = find_register(cx, body.register_code)
    rink = get_rink(cx, register["rink_code"], lock=True)
    row = cx.execute(
        "SELECT * FROM resurfacing_meter WHERE rink_code=%s AND metered_on=%s",
        (rink["code"], body.metered_on),
    ).fetchone()
    if row is None:
        raise HTTPException(409, "先登记该冰面的原始计量水票")
    measured, rolled = register_delta(body.opening_mark, body.closing_mark, register["cycle_liters"])
    difference = abs(measured - row["volume_liters"])
    state = "matched" if difference <= max(10, .05 * row["volume_liters"]) else "pending"
    recorded = cx.execute(
        """INSERT INTO meter_variance_cases
           (rink_code,metered_on,register_code,opening_mark,closing_mark,rolled,measured_liters,ledger_liters,state,evidence)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *""",
        (rink["code"],body.metered_on,body.register_code,body.opening_mark,body.closing_mark,rolled,measured,
         row["volume_liters"],state,body.evidence),
    ).fetchone()
    if recorded is None:
        raise HTTPException(409, "该水票已有表码核对记录")
    return recorded


def adjudicate(cx, code, day, verdict, actor):
    rink = get_rink(cx, code, lock=True)
    row = cx.execute(
        """SELECT c.*,m.passes FROM meter_variance_cases c JOIN resurfacing_meter m
           USING (rink_code,metered_on) WHERE c.rink_code=%s AND c.metered_on=%s""", (code,day)
    ).fetchone()
    if row is None:
        raise HTTPException(409, "先登记该水票的表码核对记录")
    if row["state"] in ("retained", "corrected"):
        if (row["state"] == "corrected") == bool(verdict.use_measured):
            # Retrying the same verdict must not recompute again or open a second suspension.
            return {**row, "shift_impacts": [], "already_resolved": True}
        raise HTTPException(409, "该水票已有不同的复核结论")
    if row["state"] != "pending":
        raise HTTPException(409, "只有未复核的差异水票可以定案")
    corrected = row["measured_liters"] if verdict.use_measured else None
    if corrected is not None and not 20 * row["passes"] <= corrected <= 1000 * row["passes"]:
        raise HTTPException(409, "表码差对应每次耗水量超出有效范围，请保留原票并记录原因")
    revised = cx.execute(
        """UPDATE meter_variance_cases SET state=%s,effective_liters=%s,resolution=%s,resolved_by=%s
           WHERE rink_code=%s AND metered_on=%s RETURNING *""",
        ("corrected" if corrected is not None else "retained",corrected,verdict.resolution,actor,code,day),
    ).fetchone()
    if corrected is not None:
        cx.execute("UPDATE ice_rinks SET meter_revision=meter_revision+1 WHERE code=%s", (code,))
        revised["meter_revision"] = rink["meter_revision"] + 1
        revised["shift_impacts"] = recompute_signed(cx, {**rink, "meter_revision": rink["meter_revision"] + 1})
    return revised
