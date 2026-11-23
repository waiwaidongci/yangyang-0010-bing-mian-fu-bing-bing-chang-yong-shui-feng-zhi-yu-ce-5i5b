CREATE TABLE IF NOT EXISTS installed_registers (
    code TEXT PRIMARY KEY,
    rink_code TEXT NOT NULL REFERENCES ice_rinks(code),
    cycle_liters INTEGER NOT NULL CHECK (cycle_liters>0),
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meter_variance_cases (
    rink_code TEXT NOT NULL,
    metered_on DATE NOT NULL,
    register_code TEXT NOT NULL REFERENCES installed_registers(code),
    opening_mark INTEGER NOT NULL CHECK (opening_mark>=0),
    closing_mark INTEGER NOT NULL CHECK (closing_mark>=0),
    rolled BOOLEAN NOT NULL,
    measured_liters INTEGER NOT NULL CHECK (measured_liters>0),
    ledger_liters INTEGER NOT NULL CHECK (ledger_liters>0),
    state TEXT NOT NULL CHECK (state IN ('matched','pending','retained','corrected')),
    evidence TEXT NOT NULL,
    effective_liters INTEGER CHECK (effective_liters>0),
    resolution TEXT,
    resolved_by TEXT,
    PRIMARY KEY(rink_code,metered_on),
    FOREIGN KEY(rink_code,metered_on) REFERENCES resurfacing_meter(rink_code,metered_on),
    CHECK ((effective_liters IS NOT NULL) = (state='corrected')),
    CHECK ((resolved_by IS NOT NULL) = (state IN ('retained','corrected')))
);
