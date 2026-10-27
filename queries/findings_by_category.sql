-- What share of sites in each site category showed each kind of finding (categories with at least :min_sites measured sites)?
SELECT category,
       COUNT(*) AS sites,
       SUM(any_incident) AS sites_with_incident,
       ROUND(100.0 * SUM(any_incident) / COUNT(*), 1) AS pct_incident,
       SUM(tracker_request) AS sites_tracker_request,
       ROUND(100.0 * SUM(tracker_request) / COUNT(*), 1) AS pct_tracker_request,
       SUM(storage) AS sites_storage,
       ROUND(100.0 * SUM(storage) / COUNT(*), 1) AS pct_storage,
       SUM(no_cmp) AS sites_no_cmp,
       SUM(consent_aware) AS sites_consent_aware
FROM site_flags
WHERE run_id = :run_id
GROUP BY category
HAVING COUNT(*) >= :min_sites
ORDER BY pct_incident DESC, category;
