-- On what share of measured sites was each tracker domain contacted before any choice?
SELECT t.tracker_domain, t.tracker_owner, t.tracker_category,
       COUNT(DISTINCT v.site_id) AS sites,
       ROUND(100.0 * COUNT(DISTINCT v.site_id)
             / (SELECT COUNT(*) FROM measured_site m WHERE m.run_id = :run_id), 1) AS pct_sites,
       SUM(t.consent_denied = 0) AS requests_without_denied_signal,
       SUM(t.consent_denied = 1) AS requests_with_denied_signal
FROM third_party_contact t JOIN visit v USING (visit_id)
WHERE v.run_id = :run_id AND v.status = 'ok' AND t.tracker_domain IS NOT NULL
GROUP BY t.tracker_domain, t.tracker_owner, t.tracker_category
ORDER BY sites DESC, t.tracker_domain;
