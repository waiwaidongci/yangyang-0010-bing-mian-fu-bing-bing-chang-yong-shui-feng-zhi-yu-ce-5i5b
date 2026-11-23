from fastapi import HTTPException


def get_survey(cx, survey_id, *, lock=False):
    row = cx.execute("SELECT * FROM ice_surveys WHERE id=%s" + (" FOR UPDATE" if lock else ""), (survey_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "冰面巡检单不存在")
    return row


def survey_map(cx):
    return cx.execute(
        """SELECT s.*,r.name AS rink_name,coalesce((SELECT jsonb_object_agg(z.zone,
                  jsonb_build_object('thickness',z.thickness_mm,'groove',z.groove_mm))
               FROM ice_survey_zones z WHERE z.survey_id=s.id),'{}') AS zones
           FROM ice_surveys s JOIN ice_rinks r ON r.code=s.rink_code
           ORDER BY s.inspected_on DESC,s.id DESC LIMIT 60"""
    ).fetchall()
