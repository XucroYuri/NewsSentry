import assert from "node:assert/strict";
import { test } from "node:test";

import { Language, collectedEventFromEntry } from "../workers/lib/collect/collected-event.ts";
import {
  classifyEvent,
  type Classification,
  type ClassificationConfig,
} from "../workers/lib/collect/classifier.ts";

/** 最小分类配置：2 个 L0 域、1 个 L1 主题、1 个 country_axis。 */
function minimalConfig(): ClassificationConfig {
  return {
    l0_domains: [
      { code: "economy", keywords_en: ["trade", "tariff", "gdp"] },
      { code: "politics", keywords_en: ["election", "parliament"] },
    ],
    l1_topics: [
      { code: "trade-policy", l0_domain: "economy", keywords_en: ["trade", "tariff"] },
    ],
    country_axes: {
      europe: { enabled: true, sub_axes: ["trade-policy"] },
    },
  };
}

/** 构造一个经济新闻事件（命中 trade/tariff）。 */
async function economyEvent() {
  return collectedEventFromEntry(
    "it",
    "ansa",
    "run-1",
    Language.IT,
    "https://feeds/ansa",
    {
      title: "EU trade tariff deal",
      link: "https://ex.com/t",
      content: "A new gdp report on trade tariffs.",
      published_at: "2024-01-01T00:00:00+00:00",
      guid: "g",
    },
  );
}

test("classifyEvent returns classifier_version rules-v1", async () => {
  const ev = await economyEvent();
  const result = classifyEvent(ev, minimalConfig());
  assert.equal(result.classifier_version, "rules-v1");
});

test("classifyEvent: L0 命中计数最高域 + confidence(命中/总词数)", async () => {
  const ev = await economyEvent();
  const result = classifyEvent(ev, minimalConfig());

  // economy 域 3 个关键词中命中 trade/tariff/gdp = 3。
  assert.equal(result.l0, "economy");
  assert.equal(result.confidence, 100); // 3/3 → 100，封顶 100
  // candidates 仅含命中数 > 0 的域，按 hits 降序，最多 3 个（对齐 Python 语义）。
  assert.deepEqual(result.candidates, [{ code: "economy", hits: 3 }]);
});

test("classifyEvent: L1 子议题在命中域下匹配", async () => {
  const ev = await economyEvent();
  const result = classifyEvent(ev, minimalConfig());

  // trade-policy 2 个关键词，命中 trade/tariff = 2 → 100%。
  assert.deepEqual(result.l1, [{ code: "trade-policy", confidence: 100 }]);
});

test("classifyEvent: L2 国家子轴取子议题平均置信度", async () => {
  const ev = await economyEvent();
  const result = classifyEvent(ev, minimalConfig());

  // europe 轴 sub_axes=[trade-policy]，其 confidence=100 → 平均 100。
  assert.deepEqual(result.l2, [{ code: "europe", confidence: 100 }]);
});

test("classifyEvent: L3 始终为空数组", async () => {
  const ev = await economyEvent();
  const result = classifyEvent(ev, minimalConfig());
  assert.deepEqual(result.l3, []);
});

test("classifyEvent: 空 l0_domains → uncategorized, confidence 0", async () => {
  const ev = await economyEvent();
  const result = classifyEvent(ev, { l0_domains: [], l1_topics: [], country_axes: {} });
  assert.equal(result.l0, "uncategorized");
  assert.equal(result.confidence, 0);
  assert.deepEqual(result.candidates, []);
});

test("classifyEvent: 未命中任何域 → uncategorized, confidence 0", async () => {
  const ev = await collectedEventFromEntry(
    "it",
    "ansa",
    "run-1",
    Language.IT,
    "https://feeds/ansa",
    {
      title: "Weather forecast",
      link: "https://ex.com/w",
      content: "Sunny and warm.",
      published_at: "2024-01-01T00:00:00+00:00",
      guid: "g",
    },
  );
  const result = classifyEvent(ev, minimalConfig());
  assert.equal(result.l0, "uncategorized");
  assert.equal(result.confidence, 0);
});

test("classifyEvent: 纯函数，不改动 event", async () => {
  const ev = await economyEvent();
  const before = JSON.stringify(ev);
  classifyEvent(ev, minimalConfig());
  assert.equal(JSON.stringify(ev), before);
});

test("classifyEvent: 命中落在 .5 边界取偶，对齐 Python round（half-to-even）", async () => {
  // domain 有 8 个关键词、命中 5 个 → 5/8*100 = 62.5 → half-to-even 得 62（而非 Math.round 的 63）。
  const config: ClassificationConfig = {
    l0_domains: [
      {
        code: "economy",
        keywords_en: ["a", "b", "c", "d", "e", "f", "g", "h"],
      },
    ],
    l1_topics: [],
    country_axes: {},
  };
  const ev = await collectedEventFromEntry(
    "it",
    "ansa",
    "run-1",
    Language.IT,
    "https://feeds/ansa",
    {
      title: "a b c d e",
      link: "https://ex.com/t",
      content: "unrelated filler words that do not hit the keyword list.",
      published_at: "2024-01-01T00:00:00+00:00",
      guid: "g",
    },
  );
  const result = classifyEvent(ev, config);
  assert.equal(result.l0, "economy");
  assert.equal(result.confidence, 62, "62.5 应 half-to-even 舍入为 62，不是 Math.round 的 63");
});
