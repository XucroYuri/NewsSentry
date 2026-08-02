-- Phase 5: isolate historical rows with implausibly future timestamps.
-- Safe to replay: active rows are deleted only after their quarantine row exists.

INSERT OR IGNORE INTO quarantined_events (
    quarantine_id,
    target_id,
    source_id,
    reason_code,
    payload_json
)
SELECT
    '20260802_phase5_future_event_quarantine:' || e.event_id,
    e.target_id,
    e.source_id,
    CASE
        WHEN datetime(e.collected_at) > datetime('now', '+5 minutes')
            THEN 'future_collected_at'
        ELSE 'future_published_at'
    END,
    json_object(
        'migration_id', '20260802_phase5_future_event_quarantine',
        'predicate_version', '2026-08-02.health-v1',
        'reason_code', CASE
            WHEN datetime(e.collected_at) > datetime('now', '+5 minutes')
                THEN 'future_collected_at'
            ELSE 'future_published_at'
        END,
        'reason_summary', json_object(
            'collected_at_future_window', '+5 minutes',
            'published_at_future_window', '+24 hours'
        ),
        'event', json_object(
            'event_id', e.event_id,
            'target_id', e.target_id,
            'target_label', e.target_label,
            'region_id', e.region_id,
            'source_id', e.source_id,
            'source_name', e.source_name,
            'source_type', e.source_type,
            'credibility_label', e.credibility_label,
            'published_at', e.published_at,
            'collected_at', e.collected_at,
            'title', e.title,
            'original_title', e.original_title,
            'summary', e.summary,
            'recommendation_reason', e.recommendation_reason,
            'full_content', e.full_content,
            'original_url', e.original_url,
            'detail_url', e.detail_url,
            'image_urls', e.image_urls,
            'tags', e.tags,
            'issue_tags', e.issue_tags,
            'related_tags', e.related_tags,
            'region_tags', e.region_tags,
            'entities', e.entities,
            'language', e.language,
            'pipeline_stage', e.pipeline_stage,
            'processing_history', e.processing_history,
            'value_label', e.value_label,
            'value_score', e.value_score,
            'china_relevance_label', e.china_relevance_label,
            'related_count', e.related_count,
            'discussion_count', e.discussion_count,
            'classification', e.classification,
            'extra', e.extra,
            'breaking_score', e.breaking_score,
            'breaking_label', e.breaking_label,
            'breaking_reason', e.breaking_reason,
            'breaking_confidence', e.breaking_confidence,
            'breaking_dimensions', e.breaking_dimensions,
            'breaking_score_version', e.breaking_score_version,
            'target_timezone', e.target_timezone,
            'published_at_local', e.published_at_local,
            'created_at', e.created_at,
            'updated_at', e.updated_at
        ),
        'localizations',
        json(COALESCE((
            SELECT json_group_array(json_object(
                'event_id', l.event_id,
                'locale', l.locale,
                'localized_title', l.localized_title,
                'localized_summary', l.localized_summary,
                'localized_recommendation_reason', l.localized_recommendation_reason,
                'localized_tags', l.localized_tags,
                'localized_issue_tags', l.localized_issue_tags,
                'localized_related_tags', l.localized_related_tags,
                'localized_region_tags', l.localized_region_tags,
                'localized_language', l.localized_language,
                'quality_score', l.quality_score,
                'model', l.model,
                'route_id', l.route_id,
                'updated_at', l.updated_at
            ))
            FROM event_localizations l
            WHERE l.event_id = e.event_id
        ), '[]'))
    )
FROM events e
WHERE datetime(e.collected_at) > datetime('now', '+5 minutes')
   OR datetime(e.published_at) > datetime('now', '+24 hours');

DELETE FROM event_localizations
WHERE EXISTS (
    SELECT 1
    FROM events e
    JOIN quarantined_events q
      ON q.quarantine_id = '20260802_phase5_future_event_quarantine:' || e.event_id
    WHERE e.event_id = event_localizations.event_id
      AND (
          datetime(e.collected_at) > datetime('now', '+5 minutes')
          OR datetime(e.published_at) > datetime('now', '+24 hours')
      )
);

DELETE FROM events
WHERE (
    datetime(collected_at) > datetime('now', '+5 minutes')
    OR datetime(published_at) > datetime('now', '+24 hours')
)
AND EXISTS (
    SELECT 1
    FROM quarantined_events q
    WHERE q.quarantine_id = '20260802_phase5_future_event_quarantine:' || events.event_id
);

INSERT OR IGNORE INTO runtime_migration_receipts (migration_id, details_json)
SELECT
    '20260802_phase5_future_event_quarantine',
    json_object(
        'predicate_version', '2026-08-02.health-v1',
        'moved_count', (
            SELECT COUNT(*)
            FROM quarantined_events
            WHERE quarantine_id LIKE '20260802_phase5_future_event_quarantine:%'
              AND reason_code IN ('future_collected_at', 'future_published_at')
        ),
        'reason_summary', json_object(
            'collected_at_future_window', '+5 minutes',
            'published_at_future_window', '+24 hours',
            'future_collected_at_count', (
                SELECT COUNT(*)
                FROM quarantined_events
                WHERE quarantine_id LIKE '20260802_phase5_future_event_quarantine:%'
                  AND reason_code = 'future_collected_at'
            ),
            'future_published_at_count', (
                SELECT COUNT(*)
                FROM quarantined_events
                WHERE quarantine_id LIKE '20260802_phase5_future_event_quarantine:%'
                  AND reason_code = 'future_published_at'
            )
        )
    );
