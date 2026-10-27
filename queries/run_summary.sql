-- When, from where and with which browser and list was a run measured, and how did its visits end?
SELECT r.run_id, r.started_at, r.finished_at, r.country, r.tool_version, r.browser_channel,
       r.browser_version, r.list_source, r.list_sha256, r.list_fetched_at, r.config_sha256,
       COUNT(v.visit_id) AS visits,
       COALESCE(SUM(v.status = 'ok'), 0) AS ok_visits,
       COALESCE(SUM(v.status = 'failed'), 0) AS failed_visits,
       COALESCE(SUM(v.status = 'http_error'), 0) AS http_error_visits,
       COALESCE(SUM(v.status = 'skipped_robots'), 0) AS skipped_visits,
       (SELECT COUNT(*) FROM measured_site m WHERE m.run_id = r.run_id) AS measured_sites,
       (SELECT COUNT(DISTINCT x.site_id) FROM visit x WHERE x.run_id = r.run_id) AS listed_sites
FROM run r LEFT JOIN visit v ON v.run_id = r.run_id
WHERE r.run_id = :run_id
GROUP BY r.run_id;
