-- What did the browser request during one visit, in the order it asked, before any interaction?
SELECT r.started_ms, r.host, r.path, r.resource_type, r.is_third_party, r.blocked_reason,
       r.tracker_owner, r.tracker_category, r.consent_signal, r.consent_denied,
       r.started_ms <= v.load_ms AS before_load, v.load_ms
FROM request_log r JOIN visit v USING (visit_id)
WHERE r.visit_id = :visit_id
ORDER BY r.started_ms, r.request_id;
