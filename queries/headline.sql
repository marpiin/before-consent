-- Of the measured sites, how many showed each kind of finding before any choice?
SELECT COUNT(*) AS sites,
       COALESCE(SUM(any_incident), 0) AS sites_with_incident,
       COALESCE(SUM(tracker_request), 0) AS sites_tracker_request,
       COALESCE(SUM(storage), 0) AS sites_storage,
       COALESCE(SUM(consent_aware), 0) AS sites_consent_aware,
       COALESCE(SUM(no_cmp), 0) AS sites_no_cmp,
       ROUND(100.0 * SUM(any_incident) / NULLIF(COUNT(*), 0), 1) AS pct_incident,
       ROUND(100.0 * SUM(tracker_request) / NULLIF(COUNT(*), 0), 1) AS pct_tracker_request,
       ROUND(100.0 * SUM(storage) / NULLIF(COUNT(*), 0), 1) AS pct_storage
FROM site_flags
WHERE run_id = :run_id;
