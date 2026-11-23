"""End-to-end checks for corrections after a shift is signed.

Requires a PostgreSQL on TEST_DATABASE_URL defaulting to the local integration instance.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("DATABASE_URL",
                      os.environ.get("TEST_DATABASE_URL", "postgresql://app:pw@127.0.0.1:55432/business"))
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6399/0")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("SEED_DEMO", "false")
os.environ.setdefault("APP_NAME", "yangyang-test")

import fakeredis
from fastapi.testclient import TestClient

import core
from core import db, seed_users

core.CACHE = fakeredis.FakeRedis()

import app as application
application.CACHE = core.CACHE

PASSWORD = "Demo2026!"
RINK = "R-T"
DAY = "2026-11-24"


@pytest.fixture()
def client():
    with db() as cx:
        cx.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    with TestClient(application.app) as test_client:
        with db() as cx:
            seed_users(cx)
            prepare_domain(cx)
        yield test_client


def login(client, role):
    response = client.post("/api/auth/login", json={"email": f"{role}@demo.local", "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def operator(client):
    return login(client, "operator")


@pytest.fixture()
def reviewer(client):
    return login(client, "reviewer")


def prepare_domain(cx):
    cx.execute(
        """INSERT INTO ice_rinks(code,name,surface_m2,tank_liters,buffer_percent)
           VALUES (%s,'测试冰',500,820,10)""", (RINK,))
    for offset in range(12):
        day = f"2026-11-{10 + offset:02d}"
        cx.execute(
            """INSERT INTO resurfacing_meter(rink_code,metered_on,passes,volume_liters,source_ticket)
               VALUES (%s,%s,2,360,%s)""", (RINK, day, f"WTR-{1100 + offset}"))
    shift = cx.execute(
        """INSERT INTO water_shifts(rink_code,operating_day,label,start_time,end_time)
           VALUES (%s,%s,'早班','06:00','14:00') RETURNING id""", (RINK, DAY)).fetchone()
    for ref, start, end, passes in (
        ("SK-1", "06:30", "07:50", 2),
        ("SK-2", "08:10", "09:00", 1),
        ("SK-3", "09:15", "10:15", 1),
    ):
        cx.execute(
            """INSERT INTO ice_bookings(shift_id,booking_ref,crew_label,start_time,end_time,passes)
               VALUES (%s,%s,'训练',%s,%s,%s)""", (shift["id"], ref, start, end, passes))
    cx.execute(
        """INSERT INTO installed_registers(code,rink_code,cycle_liters,description)
           VALUES ('REG-T',%s,10000,'测试表')""", (RINK,))
    cx.execute(
        """INSERT INTO resurfacing_crews VALUES ('CREW-T','测试机组',700,'06:00','14:00')""")


def shift_id(client, headers):
    rows = client.get("/api/shifts", headers=headers).json()
    return next(row["id"] for row in rows if row["rink_code"] == RINK)


def run_forecast(client, headers, shift):
    queued = client.post(f"/api/shifts/{shift}/forecasts", headers=headers)
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["job_id"]
    from worker import process
    with db() as cx:
        assert process(cx)
    job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
    assert job["status"] == "done", job
    return job["result"]


def sign_shift(client, headers, shift):
    report = run_forecast(client, headers, shift)
    response = client.post(f"/api/shifts/{shift}/confirm", headers=headers,
                           json={"forecast_id": report["id"]})
    assert response.status_code == 200, response.text
    return report


def state(client, headers, shift):
    return client.get(f"/api/shifts/{shift}/handover", headers=headers).json()


def start_case(client, headers, measured=440):
    response = client.post("/api/registers/checks", headers=headers, json={
        "register_code": "REG-T", "metered_on": "2026-11-21",
        "opening_mark": 1000, "closing_mark": 1000 + measured, "evidence": "抄表照片 P-1",
    })
    assert response.status_code == 201, response.text


def test_correction_pauses_and_supplement_releases(client, operator, reviewer):
    shift = shift_id(client, operator)
    signed = sign_shift(client, reviewer, shift)
    assert signed["peak_segment_liters"] == 792  # 4 passes × 198 L

    start_case(client, operator)
    corrected = client.post(f"/api/registers/checks/{RINK}/2026-11-21/resolve", headers=reviewer,
                            json={"use_measured": True, "resolution": "按表码差更正水票"})
    assert corrected.status_code == 200, corrected.text
    impact = corrected.json()["shift_impacts"][0]
    assert impact["suspended"] is True

    view = state(client, operator, shift)
    assert view["shift"]["status"] == "suspended"
    assert view["shift"]["validation_state"] == "suspended"
    assert view["executable"] is None
    assert view["signed"]["forecast"]["id"] == signed["id"]
    assert view["signed"]["evidence_current"] is False
    assert "高于原签报" in view["suspension"]["reason"]
    assert view["suspension"]["previous_peak"] == 792
    assert view["suspension"]["raised_peak"] > 792
    assert view["scheduling"] and len(view["scheduling"]) == 3

    # A paused shift cannot be signed again without a supplement.
    blocked = client.post(f"/api/shifts/{shift}/confirm", headers=reviewer,
                          json={"forecast_id": view["latest"]["id"]})
    assert blocked.status_code == 409
    assert "补单" in blocked.json()["detail"]

    # Recompute after adding a refill splits the tank run into two segments.
    bookings = client.get(f"/api/shifts/{shift}/bookings", headers=operator).json()
    second = next(row for row in bookings if row["booking_ref"] == "SK-2")
    rescheduled = client.put(f"/api/shifts/{shift}/bookings/{second['id']}", headers=operator,
                             json={"start_time": "08:10", "end_time": "09:00",
                                   "refill_reason": "水箱未满，开场前补满"})
    assert rescheduled.status_code == 200, rescheduled.text
    candidate = run_forecast(client, operator, shift)

    view = state(client, operator, shift)
    assert view["latest"]["id"] == candidate["id"]
    assert view["latest"]["within_capacity"] is True
    assert view["shift"]["status"] == "suspended"

    prepared = client.post(f"/api/shifts/{shift}/supplements", headers=operator,
                           json={"forecast_id": candidate["id"], "note": "签到前补水，重新分段"})
    assert prepared.status_code == 201, prepared.text
    order = prepared.json()
    assert order["status"] == "prepared"
    assert client.post(f"/api/shifts/{shift}/supplements", headers=operator,
                       json={"forecast_id": candidate["id"], "note": "重复补单"}
                       ).status_code == 409

    released = client.post(f"/api/shifts/{shift}/supplements/{order['id']}/sign", headers=reviewer)
    assert released.status_code == 200, released.text
    assert released.json()["shift"]["status"] == "confirmed"
    assert released.json()["shift"]["confirmed_forecast"] == candidate["id"]

    view = state(client, operator, shift)
    assert view["executable"]["id"] == candidate["id"]
    assert view["suspension"] is None
    assert view["history"][0]["released_at"] is not None
    assert view["history"][0]["supplements"][0]["status"] == "signed"


def test_over_capacity_supplement_is_returned(client, operator, reviewer):
    shift = shift_id(client, operator)
    sign_shift(client, reviewer, shift)
    start_case(client, operator)
    assert client.post(f"/api/registers/checks/{RINK}/2026-11-21/resolve", headers=reviewer,
                       json={"use_measured": True, "resolution": "按表码差更正"}
                       ).status_code == 200
    view = state(client, operator, shift)
    assert view["latest"]["within_capacity"] is False

    order = client.post(f"/api/shifts/{shift}/supplements", headers=operator,
                        json={"forecast_id": view["latest"]["id"], "note": "未补排分段"})
    assert order.status_code == 201, order.text
    denied = client.post(f"/api/shifts/{shift}/supplements/{order.json()['id']}/sign", headers=reviewer)
    assert denied.status_code == 409
    assert "超过水箱" in denied.json()["detail"]
    view = state(client, operator, shift)
    assert view["shift"]["status"] == "suspended"
    returned = view["history"][0]["supplements"][0]
    assert returned["status"] == "returned"
    assert "超过水箱" in returned["returned_reason"]
    assert view["pending_supplement"] is None

    # Adding a refill lets the operator submit a fresh order against the recomputed plan.
    bookings = client.get(f"/api/shifts/{shift}/bookings", headers=operator).json()
    second = next(row for row in bookings if row["booking_ref"] == "SK-2")
    client.put(f"/api/shifts/{shift}/bookings/{second['id']}", headers=operator,
               json={"start_time": "08:10", "end_time": "09:00", "refill_reason": "开场前补满水箱"})
    candidate = run_forecast(client, operator, shift)
    retry = client.post(f"/api/shifts/{shift}/supplements", headers=operator,
                        json={"forecast_id": candidate["id"], "note": "已补满分段"})
    assert retry.status_code == 201, retry.text
    released = client.post(f"/api/shifts/{shift}/supplements/{retry.json()['id']}/sign", headers=reviewer)
    assert released.status_code == 200, released.text
    view = state(client, operator, shift)
    assert view["shift"]["status"] == "confirmed"
    assert [s["status"] for s in view["history"][0]["supplements"]] == ["signed", "returned"]


def test_supplement_using_stale_ticket_is_returned(client, operator, reviewer):
    shift = shift_id(client, operator)
    sign_shift(client, reviewer, shift)
    start_case(client, operator)
    assert client.post(f"/api/registers/checks/{RINK}/2026-11-21/resolve", headers=reviewer,
                       json={"use_measured": True, "resolution": "按表码差更正"}
                       ).status_code == 200
    bookings = client.get(f"/api/shifts/{shift}/bookings", headers=operator).json()
    second = next(row for row in bookings if row["booking_ref"] == "SK-2")
    client.put(f"/api/shifts/{shift}/bookings/{second['id']}", headers=operator,
               json={"start_time": "08:10", "end_time": "09:00", "refill_reason": "补满分段"})
    candidate = run_forecast(client, operator, shift)
    order = client.post(f"/api/shifts/{shift}/supplements", headers=operator,
                        json={"forecast_id": candidate["id"], "note": "按当前水票"})
    assert order.status_code == 201, order.text

    # Another water ticket lands while the supplement waits for signature.
    later = client.post(f"/api/rinks/{RINK}/meter", headers=operator, json={
        "metered_on": "2026-11-22", "passes": 2, "volume_liters": 372, "source_ticket": "WTR-2001"})
    assert later.status_code == 201, later.text
    assert later.json()["shift_impacts"][0]["suspended"] is True

    refused = client.post(f"/api/shifts/{shift}/supplements/{order.json()['id']}/sign", headers=reviewer)
    assert refused.status_code == 409
    assert "最新水票" in refused.json()["detail"]
    view = state(client, operator, shift)
    assert view["shift"]["status"] == "suspended"
    returned = view["history"][0]["supplements"][0]
    assert returned["status"] == "returned"

    # The fresh forecast can be submitted once scheduling and capacity allow it.
    fresh = view["latest"]
    view = state(client, operator, shift)
    if fresh["within_capacity"]:
        retry = client.post(f"/api/shifts/{shift}/supplements", headers=operator,
                            json={"forecast_id": fresh["id"], "note": "改用最新水票重算"})
        assert retry.status_code == 201, retry.text
        released = client.post(f"/api/shifts/{shift}/supplements/{retry.json()['id']}/sign", headers=reviewer)
        assert released.status_code == 200, released.text
        assert state(client, operator, shift)["executable"]["id"] == fresh["id"]


def test_retrying_same_correction_does_not_duplicate_suspension(client, operator, reviewer):
    shift = shift_id(client, operator)
    sign_shift(client, reviewer, shift)
    start_case(client, operator)
    payload = {"use_measured": True, "resolution": "按表码差更正"}
    first = client.post(f"/api/registers/checks/{RINK}/2026-11-21/resolve", headers=reviewer, json=payload)
    assert first.status_code == 200
    second = client.post(f"/api/registers/checks/{RINK}/2026-11-21/resolve", headers=reviewer, json=payload)
    assert second.status_code == 200
    assert second.json()["already_resolved"] is True
    assert second.json()["shift_impacts"] == []
    view = state(client, operator, shift)
    assert len(view["history"]) == 1
    with db() as cx:
        meter_revision = cx.execute("SELECT meter_revision FROM ice_rinks WHERE code=%s", (RINK,)).fetchone()
    assert meter_revision["meter_revision"] == 1

    changed = client.post(f"/api/registers/checks/{RINK}/2026-11-21/resolve", headers=reviewer,
                          json={"use_measured": False, "resolution": "改判保留原票"})
    assert changed.status_code == 409


def test_suspension_blocks_dispatch(client, operator, reviewer):
    shift = shift_id(client, operator)
    sign_shift(client, reviewer, shift)
    survey = client.post("/api/surveys", headers=operator, json={
        "ticket": "ICE-1", "rink_code": RINK, "inspected_on": "2026-11-24"})
    assert survey.status_code == 201, survey.text
    for zone in ("nw", "nc", "ne", "sw", "sc", "se"):
        assert client.put(f"/api/surveys/{survey.json()['id']}/zones", headers=operator,
                          json={"zone": zone, "thickness_mm": 24, "groove_mm": 0}).status_code == 200
    assert client.post(f"/api/surveys/{survey.json()['id']}/sign", headers=reviewer).status_code == 200
    booking = client.get(f"/api/shifts/{shift}/bookings", headers=operator).json()[0]
    request = {"booking_id": booking["id"], "crew_code": "CREW-T", "survey_id": survey.json()["id"]}

    start_case(client, operator)
    client.post(f"/api/registers/checks/{RINK}/2026-11-21/resolve", headers=reviewer,
                json={"use_measured": True, "resolution": "按表码差更正"})
    halted = client.post("/api/crew-board/allocations", headers=operator, json=request)
    assert halted.status_code == 409
    assert "暂停执行" in halted.json()["detail"]

    # After a signed supplement the same booking can be dispatched.
    bookings = client.get(f"/api/shifts/{shift}/bookings", headers=operator).json()
    second = next(row for row in bookings if row["booking_ref"] == "SK-2")
    client.put(f"/api/shifts/{shift}/bookings/{second['id']}", headers=operator,
               json={"start_time": "08:10", "end_time": "09:00", "refill_reason": "开场前补满水箱"})
    candidate = run_forecast(client, operator, shift)
    order = client.post(f"/api/shifts/{shift}/supplements", headers=operator,
                        json={"forecast_id": candidate["id"], "note": "已补排分段"})
    assert order.status_code == 201, order.text
    assert client.post(f"/api/shifts/{shift}/supplements/{order.json()['id']}/sign",
                       headers=reviewer).status_code == 200
    allowed = client.post("/api/crew-board/allocations", headers=operator, json=request)
    assert allowed.status_code == 201, allowed.text


def test_suspension_keeps_schedule_editable(client, operator, reviewer):
    shift = shift_id(client, operator)
    sign_shift(client, reviewer, shift)
    start_case(client, operator)
    client.post(f"/api/registers/checks/{RINK}/2026-11-21/resolve", headers=reviewer,
                json={"use_measured": True, "resolution": "按表码差更正"})
    added = client.post(f"/api/shifts/{shift}/bookings", headers=operator, json={
        "booking_ref": "SK-9", "crew_label": "加场", "start_time": "10:30", "end_time": "11:10", "passes": 1})
    assert added.status_code == 201, added.text
    view = state(client, operator, shift)
    assert view["shift"]["status"] == "suspended"
    assert view["scheduling"][-1]["booking_ref"] == "SK-9"
    # The new booking raises the plan revision, so the paused candidate is itself stale.
    assert view["latest"]["plan_revision"] != view["shift"]["revision"]
    stale = client.post(f"/api/shifts/{shift}/supplements", headers=operator,
                        json={"forecast_id": view["latest"]["id"], "note": "未按新冰时重算"})
    assert stale.status_code == 409
    assert "最新水票" in stale.json()["detail"]
