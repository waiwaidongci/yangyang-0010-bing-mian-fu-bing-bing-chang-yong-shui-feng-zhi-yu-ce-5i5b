from datetime import date, timedelta

from forecast import evaluate, validated_history
from schedule import list_bookings

DAY = date(2026, 11, 24)
RINKS = (("R-A", "西岸主冰", 560, 820, 10), ("R-B", "东侧教学冰", 420, 560, 5))


def seed_ice_rinks(cx):
    for code, name, size, capacity, buffer in RINKS:
        rink = cx.execute(
            """INSERT INTO ice_rinks (code,name,surface_m2,tank_liters,buffer_percent)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *""",
            (code, name, size, capacity, buffer),
        ).fetchone()
        if rink is None:
            continue
        for step in range(14):
            if code == "R-B" and step == 7:
                continue
            day = DAY - timedelta(days=14 - step)
            passes = 3 + step % 3
            cx.execute(
                """INSERT INTO resurfacing_meter (rink_code,metered_on,passes,volume_liters,source_ticket)
                   VALUES (%s,%s,%s,%s,%s)""",
                (code, day, passes, passes * (135 + 2 * step), f"WTR-{day.strftime('%m%d')}"),
            )
        shift = cx.execute(
            """INSERT INTO water_shifts (rink_code,operating_day,label,start_time,end_time)
               VALUES (%s,%s,'早班','06:00','14:00') RETURNING *""", (code, DAY)
        ).fetchone()
        for ref, label, start, end, passes in (
            ("SK-216", "青少年队晨训", "06:30", "07:50", 2),
            ("SK-222", "花滑基础班", "08:00", "08:50", 2),
            ("SK-228", "自由滑冰", "08:55", "10:15", 2),
        )[: (3 if code == "R-A" else 1)]:
            cx.execute(
                """INSERT INTO ice_bookings (shift_id,booking_ref,crew_label,start_time,end_time,passes)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (shift["id"], ref, label, start, end, passes),
            )
        if code == "R-A":
            evaluate(cx, rink, shift, list_bookings(cx, shift["id"]), validated_history(cx, code, DAY))
    cx.execute(
        """INSERT INTO installed_registers VALUES
           ('REG-W','R-A',10000,'西岸回水总表'),('REG-E','R-B',10000,'东侧复冰计量表')
           ON CONFLICT DO NOTHING"""
    )
