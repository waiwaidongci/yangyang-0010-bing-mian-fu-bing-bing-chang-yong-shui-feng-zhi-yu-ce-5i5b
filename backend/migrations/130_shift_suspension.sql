-- Signed shifts can be paused after a water-ticket correction and released by a supplement order.
ALTER TABLE water_shifts ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ;
ALTER TABLE water_shifts ADD COLUMN IF NOT EXISTS suspended_reason TEXT;

DO $$
DECLARE constraint_name text;
BEGIN
    FOR constraint_name IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'water_shifts'::regclass AND contype = 'c'
          AND (pg_get_constraintdef(oid) LIKE '%confirmed_by%'
               OR conname IN ('water_shifts_status_check','shift_signing_evidence','shift_suspension_evidence'))
    LOOP
        EXECUTE format('ALTER TABLE water_shifts DROP CONSTRAINT %I', constraint_name);
    END LOOP;
END $$;

ALTER TABLE water_shifts ADD CONSTRAINT water_shifts_status_check
    CHECK (status IN ('draft','blocked','ready','confirmed','suspended'));
ALTER TABLE water_shifts ADD CONSTRAINT shift_signing_evidence CHECK (
    (status IN ('confirmed','suspended')) = (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL AND confirmed_forecast IS NOT NULL)
);
ALTER TABLE water_shifts ADD CONSTRAINT shift_suspension_evidence CHECK (
    (status='suspended') = (suspended_at IS NOT NULL AND suspended_reason IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS shift_suspensions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES water_shifts(id),
    cause TEXT NOT NULL,
    previous_forecast BIGINT NOT NULL REFERENCES water_forecasts(id),
    previous_signed_by TEXT NOT NULL,
    previous_signed_at TIMESTAMPTZ NOT NULL,
    raising_forecast BIGINT NOT NULL REFERENCES water_forecasts(id),
    previous_peak INTEGER NOT NULL CHECK (previous_peak > 0),
    raised_peak INTEGER NOT NULL CHECK (raised_peak > 0),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at TIMESTAMPTZ,
    released_by TEXT,
    supplement_id BIGINT,
    CHECK (raised_peak > previous_peak)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_suspension
    ON shift_suspensions(shift_id) WHERE released_at IS NULL;

CREATE TABLE IF NOT EXISTS supplement_orders (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES water_shifts(id),
    suspension_id BIGINT NOT NULL REFERENCES shift_suspensions(id),
    forecast_id BIGINT NOT NULL REFERENCES water_forecasts(id),
    forecast_plan_revision INTEGER NOT NULL,
    forecast_meter_revision INTEGER NOT NULL,
    peak_segment_liters INTEGER NOT NULL CHECK (peak_segment_liters > 0),
    tank_liters INTEGER NOT NULL CHECK (tank_liters > 0),
    note TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'prepared' CHECK (status IN ('prepared','signed','returned')),
    prepared_by TEXT NOT NULL,
    prepared_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    signed_by TEXT,
    signed_at TIMESTAMPTZ,
    returned_by TEXT,
    returned_at TIMESTAMPTZ,
    returned_reason TEXT,
    CHECK ((status='signed') = (signed_by IS NOT NULL AND signed_at IS NOT NULL)),
    CHECK ((status='returned') = (returned_by IS NOT NULL AND returned_at IS NOT NULL AND returned_reason IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_prepared_supplement
    ON supplement_orders(suspension_id) WHERE status='prepared';
