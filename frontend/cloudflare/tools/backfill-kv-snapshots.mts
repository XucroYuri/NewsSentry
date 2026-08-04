// 一次性回填：把 D1 public_read_snapshots 表同步到 KV。
// 用法: npx wrangler d1 execute ns-db --remote --command "SELECT key,payload_json FROM public_read_snapshots" > /tmp/snaps.json
// 处理 /tmp/snaps.json 中的 {results:[{key,payload_json}]} 并逐条写 KV。
import { kvWriteSnapshot } from "../workers/lib/kv-snapshot-store.ts";
import { readFileSync } from "node:fs";

const src = process.argv[2];
if (!src) { console.error("usage: backfill-kv-snapshots.mts <snapshots.json>"); process.exit(1); }
const parsed = JSON.parse(readFileSync(src, "utf8"));
const results = Array.isArray(parsed)
  ? parsed
  : Array.isArray(parsed?.results) ? parsed.results : [];
const kv: any = (globalThis as any).__NS_KV__;
for (const row of results) {
  if (!row?.key || !row?.payload_json) continue;
  await kvWriteSnapshot(kv, row.key, JSON.parse(row.payload_json));
  console.log(`wrote ${row.key}`);
}
console.log(`done: ${results.length} snapshots`);
