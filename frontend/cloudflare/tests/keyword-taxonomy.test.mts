import assert from "node:assert/strict";
import { test } from "node:test";

import {
  keywordMatches,
  canonicalL0,
  classificationTerms,
  isCanonicalL0,
} from "../workers/lib/collect/transform-keywords.ts";

test("canonicalL0 normalizes via legacy aliases", () => {
  assert.equal(canonicalL0("economics"), "economy");
  assert.equal(canonicalL0("SECURITY"), "public-safety");
  assert.equal(canonicalL0(""), "uncategorized");
  assert.equal(canonicalL0("politics"), "politics");
});

test("classificationTerms dedupes l0+l1, drops uncategorized", () => {
  const terms = classificationTerms({
    l0: "economy",
    l1: ["trade", "trade", "energy"],
  });
  assert.deepEqual(terms, ["economy", "trade", "energy"]);
  assert.deepEqual(classificationTerms({ l0: "uncategorized", l1: [] }), []);
});

test("keywordMatches: latin word-boundary, CJK substring, acronym case-sensitive", () => {
  assert.equal(keywordMatches("trade", "The TRADE deal is big"), true); // case-insensitive word-boundary
  assert.equal(keywordMatches("xi jinping", "xi jinping 会见"), true); // multi-word boundary
  assert.ok(keywordMatches("中国", "这是一个中国新闻")); // CJK substring
  assert.equal(keywordMatches("AI", "ai is here"), false); // acronym 2-4 upper → case-sensitive
  assert.equal(keywordMatches("AI", "AI is here"), true);
});

test("isCanonicalL0", () => {
  assert.equal(isCanonicalL0("politics"), true);
  assert.equal(isCanonicalL0("economics"), false); // legacy alias not canonical
});
