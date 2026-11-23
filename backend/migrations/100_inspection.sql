CREATE TABLE IF NOT EXISTS ice_surveys (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket TEXT NOT NULL UNIQUE,
    rink_code TEXT NOT NULL REFERENCES ice_rinks(code),
    inspected_on DATE NOT NULL,
    retest_of BIGINT REFERENCES ice_surveys(id),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','cleared','repair')),
    thickness_range NUMERIC(4,1),
    signed_by TEXT,
    signed_at TIMESTAMPTZ,
    CHECK ((status='draft') = (signed_by IS NULL)),
    CHECK ((signed_by IS NULL) = (signed_at IS NULL))
);
CREATE TABLE IF NOT EXISTS ice_survey_zones (
    survey_id BIGINT NOT NULL REFERENCES ice_surveys(id),
    zone TEXT NOT NULL CHECK (zone IN ('nw','nc','ne','sw','sc','se')),
    thickness_mm NUMERIC(4,1) NOT NULL CHECK (thickness_mm BETWEEN 1 AND 80),
    groove_mm NUMERIC(3,1) NOT NULL CHECK (groove_mm BETWEEN 0 AND 20),
    PRIMARY KEY(survey_id,zone)
);
CREATE INDEX IF NOT EXISTS rink_survey_recency ON ice_surveys(rink_code,inspected_on DESC,id DESC);
