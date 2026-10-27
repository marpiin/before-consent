-- before-consent database. Values of cookies, storage entries and URL parameters are never
-- stored; see docs/data-collected.md.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS run (
    run_id           INTEGER PRIMARY KEY,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    country          TEXT NOT NULL,        -- where the measurement was taken from, given by the operator
    tool_version     TEXT NOT NULL,
    browser_channel  TEXT NOT NULL,
    browser_version  TEXT NOT NULL,
    list_source      TEXT NOT NULL,
    list_sha256      TEXT NOT NULL,
    list_fetched_at  TEXT NOT NULL,
    config_sha256    TEXT NOT NULL,
    note             TEXT
);

CREATE TABLE IF NOT EXISTS site (
    site_id   INTEGER PRIMARY KEY,
    url       TEXT NOT NULL UNIQUE,
    category  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visit (
    visit_id      INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES run(run_id),
    site_id       INTEGER NOT NULL REFERENCES site(site_id),
    round         INTEGER NOT NULL,
    started_at    TEXT NOT NULL,
    started_unix  REAL NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'http_error', 'skipped_robots')),
    error         TEXT,                    -- cause of a failure or of a skip
    final_host    TEXT,
    http_status   INTEGER,
    load_ms       INTEGER,
    cmp           TEXT                     -- detected consent manager signals, NULL if none
);

CREATE TABLE IF NOT EXISTS request_log (
    request_id        INTEGER PRIMARY KEY,
    visit_id          INTEGER NOT NULL REFERENCES visit(visit_id),
    started_ms        INTEGER NOT NULL,    -- since the visit started
    host              TEXT NOT NULL,
    path              TEXT NOT NULL,       -- first two segments, id-like segments replaced
    resource_type     TEXT NOT NULL,
    is_third_party    INTEGER NOT NULL,
    blocked_reason    TEXT,                -- set when the guard proxy refused the connection
    param_names       TEXT NOT NULL,       -- comma-separated names, never values
    consent_signal    TEXT,                -- interpreted value, only for signals we can read
    consent_denied    INTEGER NOT NULL,
    tracker_domain    TEXT,
    tracker_owner     TEXT,
    tracker_category  TEXT
);

CREATE TABLE IF NOT EXISTS cookie (
    cookie_id       INTEGER PRIMARY KEY,
    visit_id        INTEGER NOT NULL REFERENCES visit(visit_id),
    name            TEXT NOT NULL,
    domain          TEXT NOT NULL,
    expires_unix    REAL,                  -- NULL for session cookies
    secure          INTEGER NOT NULL,
    http_only       INTEGER NOT NULL,
    same_site       TEXT NOT NULL,
    is_third_party  INTEGER NOT NULL,
    tracker_owner   TEXT,
    tracker_source  TEXT CHECK (tracker_source IN ('list', 'cookie_name'))
);

CREATE TABLE IF NOT EXISTS storage_key (
    storage_key_id  INTEGER PRIMARY KEY,
    visit_id        INTEGER NOT NULL REFERENCES visit(visit_id),
    storage         TEXT NOT NULL CHECK (storage IN ('local', 'session')),
    origin_host     TEXT NOT NULL,
    key             TEXT NOT NULL,
    is_third_party  INTEGER NOT NULL,
    tracker_owner   TEXT
);

CREATE INDEX IF NOT EXISTS visit_run ON visit(run_id, site_id);
CREATE INDEX IF NOT EXISTS request_visit ON request_log(visit_id);
CREATE INDEX IF NOT EXISTS cookie_visit ON cookie(visit_id);
CREATE INDEX IF NOT EXISTS storage_visit ON storage_key(visit_id);

-- Requests that actually left the browser to a third party. Blocked ones are not contact.
CREATE VIEW IF NOT EXISTS third_party_contact AS
SELECT * FROM request_log
WHERE is_third_party = 1 AND blocked_reason IS NULL;

-- The four categories of docs/method.md. Every row happened before any interaction, because
-- the tool never interacts with the page. Only visits with status 'ok' are classified.
CREATE VIEW IF NOT EXISTS finding AS
SELECT v.visit_id, 'storage_before_choice' AS kind, c.tracker_owner AS tracker_owner,
       'cookie ' || c.name || ' on ' || c.domain AS detail
FROM cookie c JOIN visit v USING (visit_id)
WHERE v.status = 'ok' AND c.tracker_owner IS NOT NULL
UNION ALL
SELECT v.visit_id, 'storage_before_choice', s.tracker_owner,
       s.storage || 'Storage key ' || s.key || ' on ' || s.origin_host
FROM storage_key s JOIN visit v USING (visit_id)
WHERE v.status = 'ok' AND s.tracker_owner IS NOT NULL
UNION ALL
SELECT v.visit_id, 'tracker_request_before_choice', t.tracker_owner,
       t.resource_type || ' ' || t.host || t.path
FROM third_party_contact t JOIN visit v USING (visit_id)
WHERE v.status = 'ok' AND t.tracker_owner IS NOT NULL AND t.consent_denied = 0
UNION ALL
SELECT v.visit_id, 'consent_aware_request', t.tracker_owner,
       t.resource_type || ' ' || t.host || t.path
FROM third_party_contact t JOIN visit v USING (visit_id)
WHERE v.status = 'ok' AND t.tracker_owner IS NOT NULL AND t.consent_denied = 1
UNION ALL
SELECT v.visit_id, 'no_cmp_detected', NULL, 'trackers contacted and no CMP signal found'
FROM visit v
WHERE v.status = 'ok' AND v.cmp IS NULL
  AND EXISTS (SELECT 1 FROM third_party_contact t
              WHERE t.visit_id = v.visit_id AND t.tracker_owner IS NOT NULL);

-- consent_aware_request is reported apart and is not an incident; see docs/method.md.
CREATE VIEW IF NOT EXISTS incident AS
SELECT * FROM finding WHERE kind <> 'consent_aware_request';

-- Sites with at least one successful visit in a run: the denominator of every share.
CREATE VIEW IF NOT EXISTS measured_site AS
SELECT DISTINCT v.run_id, v.site_id, s.category
FROM visit v JOIN site s USING (site_id)
WHERE v.status = 'ok';

-- A site shows a kind of finding in a run if any of its successful visits shows it.
CREATE VIEW IF NOT EXISTS site_finding AS
SELECT DISTINCT v.run_id, v.site_id, f.kind
FROM finding f JOIN visit v USING (visit_id);

-- One row per measured site with a flag for each kind of finding.
CREATE VIEW IF NOT EXISTS site_flags AS
SELECT m.run_id, m.site_id, m.category,
       COALESCE(MAX(f.kind IS NOT NULL AND f.kind <> 'consent_aware_request'), 0) AS any_incident,
       COALESCE(MAX(f.kind = 'tracker_request_before_choice'), 0) AS tracker_request,
       COALESCE(MAX(f.kind = 'storage_before_choice'), 0) AS storage,
       COALESCE(MAX(f.kind = 'consent_aware_request'), 0) AS consent_aware,
       COALESCE(MAX(f.kind = 'no_cmp_detected'), 0) AS no_cmp
FROM measured_site m
LEFT JOIN site_finding f ON f.run_id = m.run_id AND f.site_id = m.site_id
GROUP BY m.run_id, m.site_id, m.category;
