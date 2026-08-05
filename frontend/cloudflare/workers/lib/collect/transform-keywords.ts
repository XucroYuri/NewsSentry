/**
 * 关键词匹配 + 分类法兼容助手（TS 移植）。
 * 源语义对齐 Python：
 *   - `_keyword_matches`（classifier_rules.py / rules_filter.py）
 *   - `canonical_l0` / `is_canonical_l0` / `classification_terms` / `_term_text`
 *     （classification_taxonomy.py）
 */

/** 全量 CANONICAL_L0（无特殊逻辑需要，仅用于 isCanonicalL0）。 */
const CANONICAL_L0 = new Set([
  "politics",
  "economy",
  "society",
  "public-safety",
  "environment",
  "tech",
  "international-relations",
  "china-related",
  "culture",
  "sports",
  "health",
  "uncategorized",
]);

/** 全量 LEGACY_L0_ALIASES（逐一复制自 Python classification_taxonomy.py）。 */
const LEGACY_L0_ALIASES: Record<string, string> = {
  economics: "economy",
  security: "public-safety",
  international: "international-relations",
  culture_society: "society",
  environment_energy: "environment",
  china_related: "china-related",
  political: "politics",
  technology: "tech",
  energy: "environment",
  breaking_news: "uncategorized",
  other: "uncategorized",
};

/** CJK 汉字 / 假名（平假名·片假名）/ 谚文（Hangul）。 */
const CJK_RE = /[぀-ヿ㐀-鿿가-힯]/;

/** 与 Python `re.escape` 等价的正则转义。 */
function escapeRegex(keyword: string): string {
  return keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 与 Python `_is_case_sensitive_acronym` 对齐：2-4 位全大写 ASCII 词 → 大小写敏感。 */
function isCaseSensitiveAcronym(keyword: string): boolean {
  return /^[A-Z]{2,4}$/.test(keyword);
}

/**
 * 关键字匹配：对齐 Python `_keyword_matches`。
 * CJK/假名/谚文关键字 → 子串匹配；否则词边界；2-4 位全大写缩写 → 大小写敏感；
 * 其余大小写不敏感。
 */
export function keywordMatches(keyword: string, text: string): boolean {
  keyword = keyword.trim();
  if (!keyword) {
    return false;
  }
  if (CJK_RE.test(keyword)) {
    return text.toLowerCase().includes(keyword.toLowerCase());
  }
  const escaped = escapeRegex(keyword);
  if (isCaseSensitiveAcronym(keyword)) {
    return new RegExp(`\\b${escaped}\\b`).test(text);
  }
  return new RegExp(`\\b${escaped}\\b`, "i").test(text);
}

/** 规范 l0：trim + lowercase；空 → "uncategorized"；legacy 别名映射；未知 → 原样。 */
export function canonicalL0(value: string | null | undefined): string {
  const raw = String(value ?? "").trim().toLowerCase();
  if (!raw) {
    return "uncategorized";
  }
  return LEGACY_L0_ALIASES[raw] ?? raw;
}

/** l0 是否为规范值（非 legacy 别名、且属于 CANONICAL_L0）。 */
export function isCanonicalL0(value: string | null | undefined): boolean {
  const raw = String(value ?? "").trim().toLowerCase();
  return canonicalL0(raw) === raw && CANONICAL_L0.has(raw);
}

/** 提取条目文本：dict 取 code/name/label/title，否则字符串化。 */
function termText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    for (const key of ["code", "name", "label", "title"]) {
      const item = obj[key];
      if (item) {
        return String(item).trim().toLowerCase();
      }
    }
    return "";
  }
  return String(value).trim().toLowerCase();
}

/**
 * 分类术语集合：规范 l0 + 各 l1 项文本，去重保序，排除 "uncategorized"。
 * l1 可为字符串数组或单个字符串；l0 为字符串（支持 dict 形式）。
 */
export function classificationTerms(
  classification: Record<string, unknown> | null | undefined,
): string[] {
  if (!classification || typeof classification !== "object") {
    return [];
  }

  const terms: string[] = [];
  const l0 = canonicalL0(termText(classification["l0"]));
  if (l0 && l0 !== "uncategorized") {
    terms.push(l0);
  }

  let l1 = classification["l1"] ?? [];
  if (!Array.isArray(l1)) {
    l1 = [l1];
  }
  for (const item of l1 as unknown[]) {
    const text = termText(item);
    if (text) {
      terms.push(text);
    }
  }

  return [...new Set(terms)];
}
