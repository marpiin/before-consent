-- Which finished run is the most recent?
SELECT MAX(run_id) AS run_id FROM run WHERE finished_at IS NOT NULL;
