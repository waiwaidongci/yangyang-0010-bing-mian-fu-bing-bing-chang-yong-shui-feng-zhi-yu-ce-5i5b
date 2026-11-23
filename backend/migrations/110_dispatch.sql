CREATE TABLE IF NOT EXISTS resurfacing_crews (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    max_surface_m2 INTEGER NOT NULL CHECK (max_surface_m2>0),
    works_from TIME NOT NULL,
    works_until TIME NOT NULL,
    CHECK (works_from<works_until)
);
CREATE TABLE IF NOT EXISTS crew_allocations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    booking_id BIGINT NOT NULL REFERENCES ice_bookings(id),
    crew_code TEXT NOT NULL REFERENCES resurfacing_crews(code),
    survey_id BIGINT NOT NULL REFERENCES ice_surveys(id),
    plan_revision INTEGER NOT NULL,
    service_day DATE NOT NULL,
    starts TIME NOT NULL,
    ends TIME NOT NULL,
    allocated_by TEXT NOT NULL,
    revoked_at TIMESTAMPTZ,
    CHECK (starts<ends)
);
CREATE UNIQUE INDEX IF NOT EXISTS active_booking_resource
    ON crew_allocations(booking_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS crew_workday ON crew_allocations(crew_code,service_day)
    WHERE revoked_at IS NULL;
INSERT INTO resurfacing_crews VALUES
 ('CREW-A','主机一组',700,'06:00','14:00'),
 ('CREW-B','教学机组',450,'06:00','14:00')
ON CONFLICT DO NOTHING;
