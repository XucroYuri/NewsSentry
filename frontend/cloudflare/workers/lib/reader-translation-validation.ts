import { marked } from "marked";

export function translationStructure(markdown: string) {
  const links: string[] = [];
  const images: string[] = [];
  const headings: number[] = [];
  const codeFences: string[] = [];
  const tableRows: number[] = [];
  marked.walkTokens(marked.lexer(markdown), (token) => {
    if (token.type === "link") links.push(token.href);
    if (token.type === "image") images.push(token.href);
    if (token.type === "heading") headings.push(token.depth);
    if (token.type === "table") tableRows.push(token.rows.length + 1);
    if (token.type === "code" && /^ {0,3}(?:`{3,}|~{3,})/.test(token.raw)) {
      codeFences.push(token.raw.replace(/\n+$/, ""));
    }
  });
  return { links: links.sort(), images: images.sort(), headings, codeFences, tableRows };
}

export function translationDifferences(value: unknown, markdown: string): string[] {
  if (typeof value !== "string" || !value.trim() || value.length > 100_000) {
    return ["译文必须为非空且不超过 100000 字符的文本"];
  }
  const source = translationStructure(markdown);
  const output = translationStructure(value);
  const differences: string[] = [];
  for (const [key, label] of [
    ["codeFences", "代码围栏"], ["images", "图片目的地"], ["links", "链接目的地"],
    ["headings", "标题层级"], ["tableRows", "表格行数"],
  ] as const) {
    if (JSON.stringify(source[key]) === JSON.stringify(output[key])) continue;
    if (source[key].length !== output[key].length) {
      differences.push(`${label}数量 ${source[key].length}→${output[key].length}`);
    } else {
      const index = source[key].findIndex((item, position) => item !== output[key][position]);
      differences.push(`${label}第 ${index + 1} 项不一致`);
    }
  }
  return differences;
}
