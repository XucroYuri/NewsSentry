import { Readability } from "@mozilla/readability";
import { parseHTML } from "linkedom";
import TurndownService from "turndown";
import { normalizeMarkdown, ReaderError, readerUrl } from "./reader-http.ts";

export interface ExtractedArticle {
  title: string;
  lang: string;
  markdown: string;
  images: Array<{ src: string; alt?: string }>;
}

function documentFor(html: string, sourceUrl: string): Document {
  const { document } = parseHTML(html);
  Object.defineProperties(document, {
    documentURI: { value: sourceUrl }, baseURI: { value: sourceUrl }, URL: { value: sourceUrl },
  });
  return document as unknown as Document;
}

function absoluteUrl(raw: string | null, sourceUrl: string): string | null {
  if (!raw?.trim()) return null;
  try {
    return readerUrl(new URL(raw, sourceUrl).href).replace(/\(/g, "%28").replace(/\)/g, "%29");
  } catch {
    return null;
  }
}

export function extractArticle(html: string, sourceUrl: string): ExtractedArticle {
  const document = documentFor(html, sourceUrl);
  const title = document.title || new URL(sourceUrl).hostname;
  const lang = document.documentElement.lang || "und";
  let content: string | null = null;
  let articleTitle = title;
  let articleLang = lang;
  try {
    const article = new Readability(document, { charThreshold: 120, maxElemsToParse: 10_000 }).parse();
    if (article?.content && (article.textContent?.trim().length ?? 0) >= 120) {
      content = article.content;
      articleTitle = article.title || title;
      articleLang = article.lang || lang;
    }
  } catch {
    // 极端 DOM 或无法识别的页面只回退到显式正文容器，不把全页导航当新闻。
  }
  if (!content) {
    const fallback = documentFor(html, sourceUrl).querySelector("article, main, [role=main]");
    content = fallback?.outerHTML ?? null;
  }
  if (!content) throw new ReaderError(422, "EXTRACTION_FAILED", `无法提取正文，请打开原文：${sourceUrl}`);
  const cleaned = documentFor(`<html><body>${content}</body></html>`, sourceUrl).body;
  cleaned.querySelectorAll("script, style, iframe, object, embed, form, nav, header, footer, aside, noscript, template, svg").forEach((node) => node.remove());
  if ((cleaned.textContent?.trim().length ?? 0) < 120) {
    throw new ReaderError(422, "EXTRACTION_FAILED", `正文为空或过短，请打开原文：${sourceUrl}`);
  }
  cleaned.querySelectorAll("a").forEach((node) => {
    const href = absoluteUrl(node.getAttribute("href"), sourceUrl);
    if (href) node.setAttribute("href", href);
    else node.removeAttribute("href");
    node.removeAttribute("title");
  });
  const images: ExtractedArticle["images"] = [];
  cleaned.querySelectorAll("img").forEach((node) => {
    const src = absoluteUrl(node.getAttribute("data-src") || node.getAttribute("src"), sourceUrl);
    if (!src || images.length >= 40) {
      node.remove();
      return;
    }
    const alt = (node.getAttribute("alt") ?? "").replace(/[\\[\]\r\n]/g, " ").trim();
    node.setAttribute("src", src);
    node.setAttribute("alt", alt);
    node.removeAttribute("title");
    if (!images.some((image) => image.src === src)) images.push({ src, ...(alt ? { alt } : {}) });
  });
  const converter = new TurndownService({ headingStyle: "atx", codeBlockStyle: "fenced" });
  return {
    title: articleTitle, lang: articleLang, images,
    // DOM 输入避免 Workers 依赖 Node DOM parser。
    markdown: normalizeMarkdown(converter.turndown(cleaned)),
  };
}
