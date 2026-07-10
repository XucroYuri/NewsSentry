ALTER TABLE events ADD COLUMN breaking_raw_score REAL;
ALTER TABLE events ADD COLUMN breaking_percentile REAL;
ALTER TABLE events ADD COLUMN breaking_calibrated_score REAL;
ALTER TABLE events ADD COLUMN breaking_adversarial_flags TEXT DEFAULT '{}';

UPDATE events
SET
    breaking_raw_score = COALESCE(breaking_raw_score, breaking_score),
    breaking_percentile = COALESCE(breaking_percentile, breaking_score),
    breaking_calibrated_score = COALESCE(breaking_calibrated_score, breaking_score),
    breaking_score_version = COALESCE(breaking_score_version, 'breaking-v2.0')
WHERE breaking_score IS NOT NULL;

DROP INDEX IF EXISTS idx_events_public_breaking;
CREATE INDEX IF NOT EXISTS idx_events_public_breaking
ON events(
    pipeline_stage,
    breaking_calibrated_score DESC,
    breaking_score DESC,
    published_at DESC
);
