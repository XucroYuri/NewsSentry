/**
 * 端到端采集闭环 `runCollectCycle`（Phase B4 编排层）。
 *
 * 串联 B2（批次调度 + 抓取归一）、B3（过滤/分类/聚类/研判）、
 * B4（写穿 + 快照刷新 + 游标/水位推进）为一个完整采集周期。
 *
 * 只组合、不重写：所有 P0-B3/B4 逻辑均复用既有导出函数。
 * 去重语义：events 表 `ON CONFLICT(event_id)` upsert 幂等是真正的去重兜底；
 * 水位（knownIds）仅作为批内捷径，不承担唯一性。
 */

import { nextBatch } from "./batch-scheduler.ts";
import { fetchCollectedEvents } from "./fetcher.ts";
import type { CollectSource } from "./fetcher.ts";
import type { CollectedEvent } from "./collected-event.ts";
import { filterEvents } from "./filter.ts";
import type { FilterConfig } from "./filter.ts";
import { classifyEvent } from "./classifier.ts";
import type { ClassificationConfig } from "./classifier.ts";
import { assignClusters } from "./clustering.ts";
import { judgeEvent } from "./judge.ts";
import { D1KvRepo, readCursor, readProcessedWatermark } from "./ops-state.ts";
import type { KvRepo } from "./ops-state.ts";
import { writeAndRefresh } from "./write-through.ts";
import { refreshPublicReadSnapshots } from "../public-read-snapshots.ts";

/** 单次采集周期入参。 */
export interface RunCollectCycleOptions {
  repos: { targets: string[] };
  batchSize?: number;
  config: {
    filter: FilterConfig;
    classifier: ClassificationConfig;
    homeRelevanceKeywords: string[];
    targetId: string;
  };
  db: D1Database;
  refresh?: typeof refreshPublicReadSnapshots;
  fetcher?: typeof fetch;
  repo?: KvRepo;
}

/** 采集周期汇总。 */
export interface RunCollectCycleResult {
  processed: number;
  written: number;
  next_cursor: number;
  refreshed: boolean;
}

export async function runCollectCycle(
  opts: RunCollectCycleOptions,
): Promise<RunCollectCycleResult> {
  const repo = opts.repo ?? new D1KvRepo(opts.db);
  const cursor = await readCursor(repo, "collect_cursor");
  const { selected } = nextBatch(opts.repos.targets, cursor, opts.batchSize ?? 8);

  // B2：对批次内每 target 抓取 + 归一。
  const runId = `collect-cycle-${Date.now()}`;
  const collectedEvents: CollectedEvent[] = [];
  for (const target of selected) {
    // 编排层最小 feed 派生：target 即 source_id，url 为占位 feed。
    const source: CollectSource = {
      target_id: opts.config.targetId,
      source_id: target,
      url: `https://feeds.example.com/${target}`,
      language: "mixed",
    };
    const outcome = await fetchCollectedEvents(source, runId, { fetcher: opts.fetcher });
    collectedEvents.push(...outcome.events);
  }

  // B3：过滤（去重水位捷径）；真正的去重由 events upsert 幂等兜底。
  const watermark = await readProcessedWatermark(repo);
  const knownIds = new Set<string>();
  if (watermark) knownIds.add(watermark);

  const nowIso = new Date().toISOString();
  const { passed } = filterEvents(collectedEvents, opts.config.filter, knownIds, nowIso);

  // B3：分类 → 聚类 → 研判，结果写回 metadata（写穿扁平化读取）。
  const clustered = await assignClusters(passed, opts.config.targetId);
  for (const event of clustered) {
    const classification = classifyEvent(event, opts.config.classifier);
    event.metadata["classification"] = classification;
    const { judge_result, china_relevance } = judgeEvent(
      event,
      classification,
      opts.config.homeRelevanceKeywords,
    );
    event.metadata["judge_result"] = judge_result;
    event.metadata["china_relevance"] = china_relevance;
  }

  // B4：写穿 events + 推进游标 + 刷新公开快照。
  const result = await writeAndRefresh({
    db: opts.db,
    events: clustered,
    cursor,
    repo: opts.repo,
    refresh: opts.refresh,
  });

  return {
    processed: clustered.length,
    written: result.written,
    next_cursor: result.next_cursor,
    refreshed: result.refreshed,
  };
}
