from fastapi import HTTPException

from inspection_repository import get_survey
from schedule import get_rink


def create(cx, body):
    get_rink(cx, body.rink_code, lock=True)
    if body.retest_of:
        earlier = get_survey(cx, body.retest_of)
        if earlier["status"] != "repair" or earlier["rink_code"] != body.rink_code or earlier["inspected_on"] > body.inspected_on:
            raise HTTPException(409, "复检须承接同冰面的修整单且日期不能提前")
    row = cx.execute(
        """INSERT INTO ice_surveys(ticket,rink_code,inspected_on,retest_of)
           VALUES (%s,%s,%s,%s) ON CONFLICT(ticket) DO NOTHING RETURNING *""",
        (body.ticket, body.rink_code, body.inspected_on, body.retest_of),
    ).fetchone()
    if row is None:
        raise HTTPException(409, "巡检票号已使用")
    return row


def observe(cx, survey_id, body):
    if get_survey(cx, survey_id, lock=True)["status"] != "draft":
        raise HTTPException(409, "巡检已签，修改需另开复检单")
    return cx.execute(
        """INSERT INTO ice_survey_zones VALUES (%s,%s,%s,%s)
           ON CONFLICT(survey_id,zone) DO UPDATE SET thickness_mm=excluded.thickness_mm,
                      groove_mm=excluded.groove_mm RETURNING *""",
        (survey_id, body.zone, body.thickness_mm, body.groove_mm),
    ).fetchone()


def sign(cx, survey_id, reviewer):
    review = get_survey(cx, survey_id, lock=True)
    if review["status"] != "draft":
        raise HTTPException(409, "巡检已经形成签审结论")
    points = cx.execute(
        "SELECT zone,thickness_mm,groove_mm FROM ice_survey_zones WHERE survey_id=%s", (survey_id,)
    ).fetchall()
    if len(points) != 6:
        raise HTTPException(409, "六区测点齐全后才能出判断")
    min_value = min(row["thickness_mm"] for row in points)
    max_value = max(row["thickness_mm"] for row in points)
    spread = max_value - min_value
    hazards = sorted(row["zone"] for row in points
                     if not 18 <= row["thickness_mm"] <= 33 or row["groove_mm"] > 2)
    state = "cleared" if not hazards and spread <= 5 else "repair"
    row = cx.execute(
        """UPDATE ice_surveys SET status=%s,thickness_range=%s,signed_by=%s,signed_at=now()
           WHERE id=%s RETURNING *""", (state, spread, reviewer, survey_id)
    ).fetchone()
    return {**row, "hazard_zones": hazards}
