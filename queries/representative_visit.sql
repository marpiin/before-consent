-- Among successful visits with at least one tracker request, which one has the median number of them?
WITH counts AS (
    SELECT v.visit_id, v.site_id, s.category, COUNT(t.request_id) AS tracker_requests
    FROM visit v
    JOIN site s USING (site_id)
    JOIN third_party_contact t ON t.visit_id = v.visit_id AND t.tracker_owner IS NOT NULL
    WHERE v.run_id = :run_id AND v.status = 'ok'
    GROUP BY v.visit_id, v.site_id, s.category
),
ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (ORDER BY tracker_requests, visit_id) AS position,
           COUNT(*) OVER () AS total
    FROM counts
)
SELECT visit_id, site_id, category, tracker_requests
FROM ranked
WHERE position = (total + 1) / 2;
