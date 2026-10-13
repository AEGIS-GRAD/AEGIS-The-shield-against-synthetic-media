-- AEGIS Flight Recorder Query Cookbook
-- Example SQL queries for incident response, reliability feedback loops, and observability.

-- 1. Average latency per detector this week
SELECT 
    t.detector_name,
    AVG(t.latency_ms) as avg_latency_ms,
    MIN(t.latency_ms) as min_latency_ms,
    MAX(t.latency_ms) as max_latency_ms,
    COUNT(t.id) as total_calls
FROM detector_telemetry t
JOIN requests r ON t.request_id = r.id
WHERE r.timestamp >= datetime('now', '-7 days')
GROUP BY t.detector_name
ORDER BY avg_latency_ms DESC;

-- 2. Error rate per detector
SELECT 
    detector_name,
    COUNT(CASE WHEN status != 'ok' THEN 1 END) * 100.0 / COUNT(*) as error_rate_percentage,
    COUNT(*) as total_calls
FROM detector_telemetry
GROUP BY detector_name;

-- 3. Find specific requests where a detector failed (Incident Response)
SELECT 
    r.job_id,
    r.timestamp,
    r.input_file,
    t.detector_name,
    t.error
FROM requests r
JOIN detector_telemetry t ON r.id = t.request_id
WHERE t.status != 'ok';

-- 4. Deepfakes detected with high confidence but low aggregated score (Alignment Study)
SELECT 
    r.job_id,
    r.input_file,
    r.aggregated_score,
    r.aggregated_verdict,
    t.detector_name,
    t.confidence_score
FROM requests r
JOIN detector_telemetry t ON r.id = t.request_id
WHERE r.aggregated_verdict = 'benign' 
  AND t.confidence_score > 0.9;
