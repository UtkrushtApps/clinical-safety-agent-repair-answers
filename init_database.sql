CREATE TABLE IF NOT EXISTS protocols (
    study_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    phase TEXT NOT NULL,
    safety_contact TEXT NOT NULL,
    reporting_notes TEXT NOT NULL,
    protocol_version TEXT NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS trial_subjects (
    study_id TEXT NOT NULL REFERENCES protocols(study_id),
    site_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL,
    country_code TEXT NOT NULL,
    randomized_at TIMESTAMPTZ,
    PRIMARY KEY (study_id, site_id, subject_id)
);

CREATE TABLE IF NOT EXISTS visit_schedules (
    visit_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    visit_name TEXT NOT NULL,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS deviation_reports (
    deviation_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    category TEXT NOT NULL,
    narrative TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_queries (
    query_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    question TEXT NOT NULL,
    response_text TEXT,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS safety_events (
    case_id TEXT PRIMARY KEY,
    source_report_id TEXT NOT NULL,
    study_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    event_term TEXT NOT NULL,
    onset_at TIMESTAMPTZ,
    seriousness_text TEXT NOT NULL,
    narrative TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS safety_events_source_unique_idx
    ON safety_events (study_id, source_report_id);
CREATE INDEX IF NOT EXISTS safety_events_subject_idx
    ON safety_events (study_id, site_id, subject_id, received_at DESC);

CREATE TABLE IF NOT EXISTS monitor_notes (
    note_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    author_role TEXT NOT NULL,
    note_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS follow_up_work (
    work_id UUID PRIMARY KEY,
    source_report_id TEXT NOT NULL,
    study_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS physician_review_work (
    review_id UUID PRIMARY KEY,
    case_id TEXT NOT NULL UNIQUE REFERENCES safety_events(case_id),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'cancelled')),
    reviewer_role TEXT,
    review_notes TEXT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    CHECK (
        status <> 'completed'
        OR (reviewer_role = 'physician' AND reviewed_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS case_dispositions (
    case_id TEXT PRIMARY KEY REFERENCES safety_events(case_id),
    run_id UUID NOT NULL,
    status TEXT NOT NULL,
    human_review_required BOOLEAN NOT NULL,
    evidence_quality TEXT NOT NULL,
    disposition JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    agent_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS audit_events_run_idx
    ON audit_events (run_id, created_at, event_id);

-- Compatibility migrations for databases initialized by an older scaffold.
ALTER TABLE follow_up_work
    ADD COLUMN IF NOT EXISTS source_report_id TEXT NOT NULL DEFAULT '';
ALTER TABLE follow_up_work
    ADD COLUMN IF NOT EXISTS dedupe_key TEXT;
UPDATE follow_up_work SET dedupe_key = work_id::text WHERE dedupe_key IS NULL;
ALTER TABLE follow_up_work ALTER COLUMN dedupe_key SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS follow_up_work_dedupe_idx
    ON follow_up_work (dedupe_key);

INSERT INTO protocols VALUES
('VIG-204', 'Vigilanib in refractory inflammatory disease', 'III', 'safety@trial.example', 'Hospitalization, life-threatening events, and medically important events require prompt safety review. Follow the current protocol and safety plan.', '6.2', '2025-01-15T00:00:00Z'),
('ONC-117', 'Oral Noverimab combination study', 'II', 'onc-safety@trial.example', 'Assess causality and seriousness using source records. Escalate incomplete medically important reports for review.', '4.0', '2025-02-01T00:00:00Z')
ON CONFLICT (study_id) DO NOTHING;

INSERT INTO trial_subjects VALUES
('VIG-204', 'US-014', '204-014-0087', 'active', 'US', '2025-03-03T14:00:00Z'),
('VIG-204', 'US-014', '204-014-0091', 'active', 'US', '2025-03-11T15:30:00Z'),
('ONC-117', 'DE-006', '117-006-0032', 'active', 'DE', '2025-02-20T09:00:00Z')
ON CONFLICT DO NOTHING;

INSERT INTO visit_schedules VALUES
('VIS-8701', 'VIG-204', 'US-014', '204-014-0087', 'Week 12', '2025-06-02', '2025-06-06', '2025-06-04T16:20:00Z'),
('VIS-8702', 'VIG-204', 'US-014', '204-014-0091', 'Week 8', '2025-05-05', '2025-05-09', NULL),
('VIS-3204', 'ONC-117', 'DE-006', '117-006-0032', 'Cycle 4 Day 1', '2025-05-12', '2025-05-14', '2025-05-13T08:10:00Z')
ON CONFLICT DO NOTHING;

INSERT INTO deviation_reports VALUES
('DEV-4408', 'VIG-204', 'US-014', '204-014-0087', '2025-06-04T17:10:00Z', 'dose', 'Study dose was given before all post-infusion observations were entered.', 'under_review'),
('DEV-4412', 'VIG-204', 'US-014', '204-014-0091', '2025-05-10T13:00:00Z', 'visit_window', 'Week 8 visit did not occur in the planned window.', 'open')
ON CONFLICT DO NOTHING;

INSERT INTO site_queries VALUES
('QRY-9910', 'VIG-204', 'US-014', '204-014-0087', '2025-06-05T08:00:00Z', 'Confirm emergency department disposition and whether admission occurred.', 'Site states the subject remained overnight. The discharge summary has been requested.', 'answered'),
('QRY-9911', 'VIG-204', 'US-014', '204-014-0087', '2025-06-05T08:05:00Z', 'Provide investigator causality and final diagnosis.', NULL, 'open'),
('QRY-7720', 'ONC-117', 'DE-006', '117-006-0032', '2025-05-13T10:00:00Z', 'Confirm whether treatment was interrupted.', 'Treatment was held for two days and resumed.', 'closed')
ON CONFLICT DO NOTHING;

INSERT INTO safety_events VALUES
('CASE-55018', 'PORTAL-78431', 'VIG-204', 'US-014', '204-014-0087', 'syncope', '2025-06-04T18:10:00Z', 'Initial portal entry says emergency evaluation; admission is not confirmed.', 'Subject fainted after infusion and was transported to the emergency department. The reporter was unsure whether the subject was admitted.', '2025-06-04T20:03:00Z'),
('CASE-44007', 'EMAIL-22091', 'ONC-117', 'DE-006', '117-006-0032', 'neutropenia', '2025-05-11T00:00:00Z', 'Investigator described the event as medically significant.', 'Laboratory results showed neutropenia and treatment was held.', '2025-05-12T07:40:00Z')
ON CONFLICT DO NOTHING;

INSERT INTO monitor_notes VALUES
('NOTE-6102', 'VIG-204', 'US-014', '204-014-0087', '2025-06-05T12:15:00Z', 'clinical_research_associate', 'Coordinator reported an overnight stay, but the hospital record and investigator assessment are still outstanding.'),
('NOTE-6103', 'VIG-204', 'US-014', '204-014-0087', '2025-06-06T09:20:00Z', 'site_coordinator', 'Family called the stay observation rather than admission. Exact discharge time was not available.'),
('NOTE-5020', 'ONC-117', 'DE-006', '117-006-0032', '2025-05-13T15:00:00Z', 'clinical_research_associate', 'Source review matched the laboratory report and temporary treatment interruption.')
ON CONFLICT DO NOTHING;
