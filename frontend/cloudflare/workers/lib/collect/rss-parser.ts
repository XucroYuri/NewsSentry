/**
 * 自研轻量 RSS/Atom 解析器。
 *
 * 设计约束（YAGNI）：不追求完整 XML 规范，仅用正则/子串级匹配提取主流字段，
 * 足以解析主流 RSS 2.0 与 Atom feeds。不使用任何外部 XML/RSS 库。
 */

export interface FeedEntry {
  title: string;
  link: string;
  content: string;
  published_at: string;
  guid: string;
}

export interface ParsedFeed {
  title: string;
  link: string;
  entries: FeedEntry[];
}

const EMPTY_FEED: ParsedFeed = { title: "", link: "", entries: [] };

/** 解码常见 HTML 实体（贪心、逐个替换，足够覆盖主流 feed 内容）。 */
function decodeEntities(text: string): string {
  return text
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&apos;", "'")
    .replaceAll("&nbsp;", " ");
}

/**
 * 从字符串中提取首个匹配 `<tag>` 与 `</tag>` 之间的内容（含自闭合 `/>` 标签）。
 * 返回 null 表示找不到标签。
 */
function extract(content: string, tag: string): string | null {
  // 匹配开放标签（允许空格/属性）。跳过自闭合 `<tag .../>`。
  const open = new RegExp(`<${tag}\\b[^>]*?>`);
  const close = new RegExp(`</${tag}\\s*>`);
  const m = open.exec(content);
  if (!m) return null;
  const rest = content.slice(m.index + m[0].length);
  const c = close.exec(rest);
  if (!c) return null;
  return rest.slice(0, c.index);
}

/** 解析单个 XML 块中的一个文本元素（tag → 解码后的内容，找不到返回 ""）。 */
function textOf(block: string, ...tags: string[]): string {
  for (const tag of tags) {
    const v = extract(block, tag);
    if (v !== null && v !== undefined) {
      const t = decodeEntities(v).trim();
      if (t.length > 0) return t;
    }
  }
  return "";
}

/** 解析 `<link>` 元素的值：文本内容优先，其次 href 属性（Atom 风格）。 */
function linkOf(block: string): string {
  const open = new RegExp(`<link\\b[^>]*>`);
  const close = new RegExp(`</link\\s*>`);
  const m = open.exec(block);
  if (!m) return "";
  const tag = m[0];
  const rest = block.slice(m.index + m[0].length);
  const c = close.exec(rest);
  if (c) {
    const inner = rest.slice(0, c.index);
    const t = decodeEntities(inner).trim();
    if (t.length > 0) return t;
  }
  // 自闭合或文本为空：取 href 属性
  const href = /\bhref\s*=\s*["']([^"']*)["']/.exec(tag);
  if (href) return decodeEntities(href[1]);
  return "";
}

/** 解析单个 entry/item 的所有字段。 */
function parseEntry(block: string, isAtom: boolean): FeedEntry {
  const title = textOf(block, "title");
  const link = linkOf(block);
  // 内容优先顺序：RSS 用 content:encoded > description；Atom 用 content > summary。
  const content = isAtom ? textOf(block, "content", "summary") : textOf(block, "content:encoded", "description");
  const published = isAtom
    ? textOf(block, "published", "updated")
    : textOf(block, "pubDate");
  const guid = isAtom ? textOf(block, "id") : textOf(block, "guid");
  return { title, link, content, published_at: published, guid };
}

export function parseFeed(xml: string): ParsedFeed {
  if (!xml || typeof xml !== "string") return EMPTY_FEED;
  if (!/<(rss|feed)\b/i.test(xml)) return EMPTY_FEED;

  const isAtom = /<feed\b/i.test(xml);

  // channel/feed 级别的 title 与 link 总是先于 item/entry 出现，取首个即可。
  const title = textOf(xml, "title");
  const link = linkOf(xml);
  const entryOpen = isAtom ? "<entry" : "<item";
  const entryClose = isAtom ? "</entry" : "</item";

  const entries: FeedEntry[] = [];
  let pos = 0;
  const openReg = new RegExp(entryOpen + "\\b[^>]*>");
  const closeReg = new RegExp(entryClose + "\\s*>");
  while (true) {
    const m = openReg.exec(xml.slice(pos));
    if (!m) break;
    const start = pos + m.index;
    const after = start + m[0].length;
    const c = closeReg.exec(xml.slice(after));
    if (!c) break;
    const end = after + c.index;
    entries.push(parseEntry(xml.slice(after, end), isAtom));
    pos = end + c[0].length;
  }

  return { title, link, entries };
}
