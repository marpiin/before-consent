-- For each listed site, how did its visits end and what did the successful ones show?
SELECT s.site_id, s.url, s.category,
       SUM(v.status = 'ok') AS ok_visits,
       SUM(v.status <> 'ok') AS other_visits,
       MAX(CASE WHEN v.status <> 'ok' THEN v.error END) AS last_problem,
       (SELECT COUNT(DISTINCT t.tracker_domain)
        FROM third_party_contact t JOIN visit x USING (visit_id)
        WHERE x.run_id = :run_id AND x.site_id = s.site_id AND x.status = 'ok') AS tracker_domains,
       (SELECT GROUP_CONCAT(kind, ' ')
        FROM (SELECT kind FROM site_finding f
              WHERE f.run_id = :run_id AND f.site_id = s.site_id
              ORDER BY kind)) AS finding_kinds,
       MAX(v.cmp) AS cmp
FROM site s JOIN visit v ON v.site_id = s.site_id AND v.run_id = :run_id
GROUP BY s.site_id, s.url, s.category
ORDER BY s.category, s.url;
