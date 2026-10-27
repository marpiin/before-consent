-- When a site shows a kind of finding, does it show it in every successful round or only in some?
WITH ok AS (
    SELECT site_id, COUNT(*) AS ok_visits
    FROM visit
    WHERE run_id = :run_id AND status = 'ok'
    GROUP BY site_id
),
seen AS (
    SELECT v.site_id, f.kind, COUNT(DISTINCT v.visit_id) AS visits
    FROM finding f JOIN visit v USING (visit_id)
    WHERE v.run_id = :run_id
    GROUP BY v.site_id, f.kind
)
SELECT seen.kind,
       COUNT(*) AS sites,
       SUM(seen.visits = ok.ok_visits) AS sites_every_round,
       SUM(seen.visits < ok.ok_visits) AS sites_some_rounds,
       ROUND(100.0 * SUM(seen.visits = ok.ok_visits) / COUNT(*), 1) AS pct_every_round
FROM seen JOIN ok USING (site_id)
GROUP BY seen.kind
ORDER BY seen.kind;
