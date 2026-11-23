CREATE TABLE IF NOT EXISTS ice_rinks (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    surface_m2 INTEGER NOT NULL CHECK (surface_m2 > 0),
    tank_liters INTEGER NOT NULL CHECK (tank_liters > 0),
    buffer_percent INTEGER NOT NULL CHECK (buffer_percent BETWEEN 0 AND 25),
    meter_revision INTEGER NOT NULL DEFAULT 0 CHECK (meter_revision >= 0)
);

CREATE TABLE IF NOT EXISTS resurfacing_meter (
    rink_code TEXT NOT NULL REFERENCES ice_rinks(code),
    metered_on DATE NOT NULL,
    passes INTEGER NOT NULL CHECK (passes BETWEEN 1 AND 24),
    volume_liters INTEGER NOT NULL CHECK (volume_liters > 0),
    source_ticket TEXT NOT NULL,
    PRIMARY KEY (rink_code, metered_on),
    UNIQUE (rink_code, source_ticket),
    CHECK (volume_liters BETWEEN 20 * passes AND 1000 * passes)
);

CREATE TABLE IF NOT EXISTS water_shifts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rink_code TEXT NOT NULL REFERENCES ice_rinks(code),
    operating_day DATE NOT NULL,
    label TEXT NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','blocked','ready','confirmed')),
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    confirmed_forecast BIGINT,
    UNIQUE (rink_code, operating_day, label),
    CHECK (start_time < end_time),
    CHECK ((status='confirmed') = (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL AND confirmed_forecast IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS ice_bookings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES water_shifts(id),
    booking_ref TEXT NOT NULL,
    crew_label TEXT NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    passes INTEGER NOT NULL CHECK (passes BETWEEN 1 AND 4),
    refill_reason TEXT,
    CHECK (start_time < end_time),
    UNIQUE (shift_id, booking_ref)
);

CREATE TABLE IF NOT EXISTS water_forecasts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES water_shifts(id),
    plan_revision INTEGER NOT NULL,
    meter_revision INTEGER NOT NULL,
    model TEXT NOT NULL CHECK (model IN ('holt','last')),
    projected_liters_per_pass INTEGER NOT NULL CHECK (projected_liters_per_pass > 0),
    peak_segment_liters INTEGER NOT NULL CHECK (peak_segment_liters > 0),
    within_capacity BOOLEAN NOT NULL,
    backtest JSONB NOT NULL,
    segments JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    ALTER TABLE water_shifts ADD CONSTRAINT shift_confirmed_evidence
        FOREIGN KEY (confirmed_forecast) REFERENCES water_forecasts(id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
