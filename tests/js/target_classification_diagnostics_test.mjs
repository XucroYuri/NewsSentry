import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync("src/news_sentry/static/pages/target_workbench.js", "utf8")
  .replace(/import\s*\{[\s\S]*?\}\s*from\s+["']\.\.\/api\.js\?v=[^"']+["'];/, `
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");
const api = async () => ({});
const apiPost = async () => ({});
const apiPatch = async () => ({});
const apiPut = async () => ({});
const showError = () => {};
const showInfo = () => {};
const showSuccess = () => {};
const state = {};
`);

const moduleUrl = `data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`;
const { classificationDiagnosticsHtml } = await import(moduleUrl);

const html = classificationDiagnosticsHtml({
  distribution: {
    "international-relations": 3,
    uncategorized: 2,
  },
  uncategorized_count: 2,
});

assert.match(html, /international-relations/);
assert.match(html, /未分类/);
assert.match(html, /<strong>2<\/strong>/);

console.log("target classification diagnostics tests passed");
