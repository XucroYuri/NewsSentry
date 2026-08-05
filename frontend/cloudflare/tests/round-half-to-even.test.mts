import assert from "node:assert/strict";
import { test } from "node:test";

import { roundHalfToEven } from "../workers/lib/collect/round-half-to-even.ts";

test("roundHalfToEven: 非 .5 边界走普通四舍五入", () => {
  assert.equal(roundHalfToEven(0.4), 0);
  assert.equal(roundHalfToEven(0.6), 1);
  assert.equal(roundHalfToEven(1.3), 1);
});

test("roundHalfToEven: .5 边界取偶（banker's rounding，对齐 Python round）", () => {
  assert.equal(roundHalfToEven(62.5), 62); // 向下
  assert.equal(roundHalfToEven(63.5), 64); // 向上
  assert.equal(roundHalfToEven(92.5), 92); // 向下
  assert.equal(roundHalfToEven(2.5), 2); // 向下
  assert.equal(roundHalfToEven(3.5), 4); // 向上
});

test("roundHalfToEven: 负数 .5 边界同样取偶", () => {
  assert.equal(roundHalfToEven(-2.5), -2);
  assert.equal(roundHalfToEven(-3.5), -4);
});
