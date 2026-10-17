-- 公开列表 / 总数 / 标签统计的时间窗是：
--   pipeline_stage = 'drafts'
--   AND published_at >= now-7d
--   AND published_at <= now+24h
-- idx_events_public_breaking 的列序是 (pipeline_stage, breaking_score, published_at)，
-- published_at 前面隔着 breaking_score，范围条件用不上；且线上 pipeline_stage 全是 drafts。
-- 无 ANALYZE 统计时，仅有 published_at 单列索引也不会被选中。
-- 本索引让等式前缀 + 时间范围一起走，COUNT(*) 可以覆盖扫描。
-- 不要在业务高峰执行。回滚：DROP INDEX IF EXISTS idx_events_public_stage_published_at;
CREATE INDEX IF NOT EXISTS idx_events_public_stage_published_at
ON events(pipeline_stage, published_at);
