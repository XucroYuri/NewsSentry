import assert from "node:assert/strict";
import { test } from "node:test";

import { Language, collectedEventFromEntry } from "../workers/lib/collect/collected-event.ts";
import type { CollectedEvent } from "../workers/lib/collect/collected-event.ts";
import type { Classification } from "../workers/lib/collect/classifier.ts";
import { judgeEvent } from "../workers/lib/collect/judge.ts";

/** 构造一个已带 filter_score 的采集事件。 */
async function scoredEvent(score: number, title?: string, content?: string): Promise<CollectedEvent> {
  const ev = await collectedEventFromEntry(
    "it",
    "ansa",
    "run-1",
    Language.IT,
    "https://feeds/ansa",
    {
      title: title ?? "A normal news headline",
      link: "https://ex.com/t",
      content: content ?? "Some body text without strong keywords.",
      published_at: "2024-01-01T00:00:00+00:00",
      guid: "g",
    },
  );
  ev.metadata["filter_score"] = score;
  return ev;
}

/** 构造一个分类结果。 */
function clazz(l0 = "other", confidence = 50, l1: string[] = []): Classification {
  return {
    l0,
    confidence,
    candidates: [],
    l1: l1.map((code) => ({ code, confidence })),
    l2: [],
    l3: [],
    classifier_version: "rules-v1",
  } as unknown as Classification;
}

test("judgeEvent: score>=80 → publish, high_value flag, 推荐发布片段", async () => {
  const ev = await scoredEvent(85);
  const result = judgeEvent(ev, clazz("other"), []);
  assert.equal(result.judge_result.recommendation, "publish");
  assert.ok(result.judge_result.flags.includes("high_value"));
  assert.ok(result.judge_result.rationale.includes("推荐发布"));
  assert.ok(result.judge_result.rationale.includes("新闻价值评分: 85/100"));
});

test("judgeEvent: l0 breaking_news → publish 且带 breaking flag", async () => {
  const ev = await scoredEvent(10);
  const result = judgeEvent(ev, clazz("breaking_news"), []);
  assert.equal(result.judge_result.recommendation, "publish");
  assert.ok(result.judge_result.flags.includes("breaking"));
});

test("judgeEvent: l0 china_related → publish（无需高分）", async () => {
  const ev = await scoredEvent(20);
  const result = judgeEvent(ev, clazz("china_related"), []);
  assert.equal(result.judge_result.recommendation, "publish");
});

test("judgeEvent: score>=60 → review, priority_topic flag", async () => {
  const ev = await scoredEvent(70);
  const result = judgeEvent(ev, clazz("other"), []);
  assert.equal(result.judge_result.recommendation, "review");
  assert.ok(result.judge_result.rationale.includes("建议审核"));
});

test("judgeEvent: l0 economy → review 且带 priority_topic flag", async () => {
  const ev = await scoredEvent(40);
  const result = judgeEvent(ev, clazz("economy"), []);
  assert.equal(result.judge_result.recommendation, "review");
  assert.ok(result.judge_result.flags.includes("priority_topic"));
});

test("judgeEvent: score<30 → discard, 可丢弃片段", async () => {
  const ev = await scoredEvent(20);
  const result = judgeEvent(ev, clazz("other"), []);
  assert.equal(result.judge_result.recommendation, "discard");
  assert.ok(result.judge_result.rationale.includes("可丢弃"));
});

test("judgeEvent: score in [30,60) → archive, 归档片段", async () => {
  const ev = await scoredEvent(50);
  const result = judgeEvent(ev, clazz("other"), []);
  assert.equal(result.judge_result.recommendation, "archive");
  assert.ok(result.judge_result.rationale.includes("归档"));
});

test("judgeEvent: home_relevance 命中关键词 ×10 顶 100（fallback 关键词 china）", async () => {
  const ev = await scoredEvent(50, "China economy report", "Beijing policy on china and sino");
  const result = judgeEvent(ev, clazz("other"), []);
  // 子串命中按「不同关键字有则计 1」：china + beijing = 2 个不同关键字 → 20
  assert.equal(result.china_relevance, 20);
  assert.equal(result.judge_result.recommendation, "archive");
});

test("judgeEvent: home_relevance ≥30 触发 home_related flag 且 rationale 含本国关联度", async () => {
  // 子串命中按「有则计 1」；单关键词重复不累计。
  const ev2 = await scoredEvent(50, "cina cina cina cina cina", "pechino pechino pechino pechino pechino");
  const r2 = judgeEvent(ev2, clazz("other"), ["cina", "pechino"]);
  // cina + pechino = 2 个不同关键字命中 → 20，未达 30（不触发 home_related）。
  assert.equal(r2.china_relevance, 20);
  assert.ok(!r2.judge_result.flags.includes("home_related"));

  // 10 个不同 fallback 关键字 → 100，触发 home_related + home_significant。
  const ev3 = await scoredEvent(
    50,
    "cina china cinese chinese pechino beijing shanghai",
    "xi jinping belt and road brics",
  );
  const r3 = judgeEvent(ev3, clazz("other"), []);
  assert.equal(r3.china_relevance, 100);
  assert.ok(r3.judge_result.flags.includes("home_related"));
  assert.ok(r3.judge_result.flags.includes("home_significant"));
  assert.ok(r3.judge_result.rationale.includes("本国关联度: 100/100"));
});

test("judgeEvent: home_relevance 顶 100", async () => {
  // 子串命中是「有则计 1」，每命中不同关键词 +10；用 10 个不同 fallback 关键词封顶。
  const ev = await scoredEvent(
    50,
    "cina china cinese chinese pechino beijing shanghai xi jinping belt and road brics",
    "",
  );
  const result = judgeEvent(ev, clazz("other"), []);
  assert.equal(result.china_relevance, 100);
});

test("judgeEvent: 自定义 homeRelevanceKeywords 覆盖 fallback", async () => {
  const ev = await scoredEvent(50, "car machine engine", "motor");
  const rFallback = judgeEvent(ev, clazz("other"), []);
  assert.equal(rFallback.china_relevance, 0);
  const rCustom = judgeEvent(ev, clazz("other"), ["car", "motor"]);
  assert.equal(rCustom.china_relevance, 20);
});

test("judgeEvent: confidence 取自 classification.confidence ?? 50", async () => {
  const ev = await scoredEvent(50);
  const result = judgeEvent(ev, clazz("political", 72), []);
  assert.equal(result.judge_result.confidence, 72);
  const ev2 = await scoredEvent(50);
  const r2 = judgeEvent(ev2, clazz("political", 0), []);
  // confidence 0 是合法值，不触发 ?? 50
  assert.equal(r2.judge_result.confidence, 0);
});

test("judgeEvent: rationale 主题段含 L1 codes（最多 3 个）", async () => {
  const ev = await scoredEvent(70);
  const result = judgeEvent(ev, clazz("economy", 60, ["trade-policy", "tariffs"]), []);
  assert.ok(result.judge_result.rationale.includes("主题: trade-policy, tariffs"));
});

test("judgeEvent: 纯函数，不改动 event", async () => {
  const ev = await scoredEvent(50);
  const before = JSON.stringify(ev);
  judgeEvent(ev, clazz("political"), []);
  assert.equal(JSON.stringify(ev), before);
});

test("judgeEvent: score 缺省（无 filter_score）按 0 处理 → discard", async () => {
  const ev = await collectedEventFromEntry(
    "it",
    "ansa",
    "run-1",
    Language.IT,
    "https://feeds/ansa",
    {
      title: "no score here",
      link: "https://ex.com/ns",
      content: "nothing",
      published_at: "2024-01-01T00:00:00+00:00",
      guid: "g",
    },
  );
  const result = judgeEvent(ev, clazz("other"), ["china"]);
  assert.equal(result.judge_result.recommendation, "discard");
});
