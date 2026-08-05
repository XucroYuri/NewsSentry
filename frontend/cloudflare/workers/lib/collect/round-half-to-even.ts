/**
 * Python 兼容的 `round()`：半进位使用 "银行家舍入"（round half to even）。
 *
 * 对齐 Python `round(x)`（float 返回 float；此处返回 number）。
 * 在恰好 `.5` 边界（hits/total*100 = x.5）时，`Math.round` 向上取整、Python 取偶，
 * 两者会分歧。此 helper 保证行为一致性。
 */

/** Python-compatible `round()`: round half to even. */
export function roundHalfToEven(n: number): number {
  const floor = Math.floor(n);
  const frac = n - floor;
  if (frac !== 0.5) return Math.round(n);
  return floor % 2 === 0 ? floor : floor + 1;
}
