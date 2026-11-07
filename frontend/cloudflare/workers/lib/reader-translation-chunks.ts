import { marked } from "marked";
import { ReaderError } from "./reader-http.ts";

export const TRANSLATION_CHUNK_CHARS = 4000;
export const TRANSLATION_MAX_CHUNKS = 32;
export const TRANSLATION_PLAN_VERSION = "markdown-blocks-v1";

export function splitTranslationMarkdown(markdown: string, target = TRANSLATION_CHUNK_CHARS): string[] {
  if (!Number.isSafeInteger(target) || target < 256) throw Error("invalid chunk target");
  const tokens = marked.lexer(markdown);
  const protectedRanges: Array<[number, number]> = [];
  let fence: { start: number; marker: string } | undefined;
  for (const line of markdown.matchAll(/^.*(?:\n|$)/gm)) {
    const marker = line[0].match(/^[ \t]*(?:>[ \t]*)*(?:(?:[-+*]|\d+[.)])[ \t]+)?(`{3,}|~{3,})(.*)/);
    if (!marker) continue;
    if (!fence) fence = { start: line.index, marker: marker[1] };
    else if (marker[1][0] === fence.marker[0] && marker[1].length >= fence.marker.length && !marker[2].trim()) {
      protectedRanges.push([fence.start, line.index + line[0].length]);
      fence = undefined;
    }
  }
  if (fence) protectedRanges.push([fence.start, markdown.length]);
  marked.walkTokens(tokens, (token) => {
    if (!["link", "image", "code", "codespan", "html", "escape"].includes(token.type)) return;
    let offset = markdown.indexOf(token.raw);
    while (offset >= 0 && token.raw.length) {
      protectedRanges.push([offset, offset + token.raw.length]);
      offset = markdown.indexOf(token.raw, offset + token.raw.length);
    }
  });
  const normalizeLabel = (label: string) => label.replace(/\s+/g, " ").trim().toLowerCase();
  for (const definition of markdown.matchAll(/^ {0,3}\[([^\]\n]+)\]:[^\n]*(?:\n|$)/gm)) {
    const label = normalizeLabel(definition[1]);
    for (const reference of markdown.matchAll(/!?\[([^\]\n]+)\](?:\[([^\]\n]*)\])?(?!\()/g)) {
      if (normalizeLabel(reference[2] || reference[1]) === label) {
        protectedRanges.push([
          Math.min(definition.index, reference.index),
          Math.max(definition.index + definition[0].length, reference.index + reference[0].length),
        ]);
      }
    }
  }
  const safe = (offset: number) => !protectedRanges.some(([start, end]) => start < offset && offset < end);
  const boundaries = new Set<number>();
  let cursor = 0;
  for (const token of tokens) {
    const offset = markdown.indexOf(token.raw, cursor);
    if (offset < 0) throw Error("Markdown token offset unavailable");
    if (offset > cursor && safe(offset)) boundaries.add(offset);
    cursor = offset + token.raw.length;
    if (safe(cursor)) boundaries.add(cursor);
    if (token.raw.length > target) {
      for (const match of token.raw.matchAll(/\n|[.!?。！？](?:[ \t]+|(?=[\p{Script=Han}]))/gu)) {
        const boundary = offset + match.index + match[0].length;
        if (safe(boundary)) boundaries.add(boundary);
      }
    }
  }
  boundaries.add(markdown.length);
  const points = [...boundaries].sort((left, right) => left - right);
  const chunks: string[] = [];
  let start = 0;
  while (start < markdown.length) {
    const remaining = points.filter((point) => point > start);
    const end = remaining.filter((point) => point <= start + target).at(-1) ?? remaining[0];
    const piece = markdown.slice(start, end);
    if (piece.trim()) chunks.push(piece);
    else if (chunks.length) chunks[chunks.length - 1] += piece;
    else {
      const next = remaining.find((point) => markdown.slice(start, point).trim());
      if (next === undefined) throw Error("empty Markdown");
      chunks.push(markdown.slice(start, next));
      start = next;
      continue;
    }
    start = end;
  }
  if (chunks.length > TRANSLATION_MAX_CHUNKS) {
    throw new ReaderError(422, "TRANSLATION_TOO_MANY_CHUNKS", "文章分段过多，请缩短原文。");
  }
  if (chunks.join("") !== markdown) throw Error("Markdown chunk reconstruction failed");
  return chunks;
}
