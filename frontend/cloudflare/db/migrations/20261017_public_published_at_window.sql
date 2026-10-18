-- 公开列表 / 总数 / 标签统计的时间窗是：
--   pipeline_stage = 'drafts'
--   AND published_at >= now-7d
--   AND published_at <= now+24h
-- idx_events_public_breaking 的列序是 (pipeline_stage, breaking_score, published_at)，
-- published_at 前面隔着 breaking_score，范围条件用不上；且线上 pipeline_stage 全是 drafts。
-- 无 ANALYZE 统计时，仅有 published_at 单列索引也不会被选中。
-- 本索引让等式前缀 + 时间范围一起走，COUNT(*) 可以覆盖扫描。
-- published_at 用 DESC：公开列表是 ORDER BY published_at DESC。
-- 预览库实测降序后 COUNT 变成只扫索引的 covering，估算读取比当前计划少约 90%。
-- 本地 node:sqlite 同样选中这条 DESC 索引：COUNT 为 COVERING，
-- 列表沿索引正序 Next，而不是对升序索引做 Prev 反向扫描。
-- CREATE INDEX IF NOT EXISTS 不会改写已存在的同名索引。
-- 不要在业务高峰执行。上线先 DROP INDEX IF EXISTS idx_events_public_stage_published_at; 再执行本文件。
-- 回滚：DROP INDEX IF EXISTS idx_events_public_stage_published_at;
CREATE INDEX IF NOT EXISTS idx_events_public_stage_published_at
ON events(pipeline_stage, published_at DESC);
