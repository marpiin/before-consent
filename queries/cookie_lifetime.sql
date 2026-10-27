-- How long are the tracker cookies found before any choice set to last?
WITH tracker_cookie AS (
    SELECT c.name, v.site_id,
           CASE
               WHEN c.expires_unix IS NULL THEN 0
               WHEN c.expires_unix - v.started_unix < 86400 THEN 1
               WHEN c.expires_unix - v.started_unix < 30 * 86400 THEN 2
               WHEN c.expires_unix - v.started_unix < 365 * 86400 THEN 3
               ELSE 4
           END AS bucket
    FROM cookie c JOIN visit v USING (visit_id)
    WHERE v.run_id = :run_id AND v.status = 'ok' AND c.tracker_owner IS NOT NULL
)
SELECT CASE bucket
           WHEN 0 THEN 'session'
           WHEN 1 THEN 'under 1 day'
           WHEN 2 THEN '1 to 30 days'
           WHEN 3 THEN '30 days to 1 year'
           ELSE '1 year or more'
       END AS lifetime,
       COUNT(*) AS cookies,
       COUNT(DISTINCT name) AS cookie_names,
       COUNT(DISTINCT site_id) AS sites
FROM tracker_cookie
GROUP BY bucket
ORDER BY bucket;
