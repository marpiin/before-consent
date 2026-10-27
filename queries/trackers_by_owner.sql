-- Which companies own the trackers contacted before any choice, and on how many sites?
SELECT t.tracker_owner,
       COUNT(DISTINCT t.tracker_domain) AS tracker_domains,
       COUNT(DISTINCT v.site_id) AS sites,
       COUNT(*) AS requests,
       SUM(t.consent_denied = 1) AS requests_with_denied_signal
FROM third_party_contact t JOIN visit v USING (visit_id)
WHERE v.run_id = :run_id AND v.status = 'ok' AND t.tracker_owner IS NOT NULL
GROUP BY t.tracker_owner
ORDER BY sites DESC, requests DESC, t.tracker_owner;
