import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import type { ReaderTranslationJobsEnv } from "../workers/lib/reader-translate-jobs.ts";

export class TranslationKV {
  entries = new Map<string, string>();
  async get(key: string, type: string) {
    const value = this.entries.get(key);
    return value === undefined ? null : type === "json" ? JSON.parse(value) : value;
  }
  async put(key: string, value: string) { this.entries.set(key, value); }
}

export function translationFixture(extra: Record<string, unknown> = {}) {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(readFileSync(new URL("../db/migrations/20261107_reader_translation_jobs.sql", import.meta.url), "utf8"));
  sqlite.exec(readFileSync(new URL("../db/migrations/20261107_reader_translation_chunks.sql", import.meta.url), "utf8"));
  const queue: Array<{ jobId: string; generation: number; chunk_index?: number }> = [];
  const delays: Array<number | undefined> = [];
  const db = {
    withSession(constraint: string) {
      if (constraint !== "first-primary") throw Error("primary session required");
      return this;
    },
    prepare(sql: string) {
      return {
        bind(...values: unknown[]) {
          return {
            sql, values,
            async first() { return sqlite.prepare(sql).get(...values) ?? null; },
            async all() { return { results: sqlite.prepare(sql).all(...values) }; },
            async run() {
              const result = sqlite.prepare(sql).run(...values);
              return { success: true, meta: { changes: Number(result.changes) } };
            },
          };
        },
      };
    },
    async batch(statements: Array<{ sql: string; values: unknown[] }>) {
      sqlite.exec("SAVEPOINT translation_batch");
      try {
        const results = statements.map(({ sql, values }) => ({
          results: sqlite.prepare(sql).all(...values), success: true, meta: {},
        }));
        sqlite.exec("RELEASE translation_batch");
        return results;
      } catch (error) {
        sqlite.exec("ROLLBACK TO translation_batch");
        sqlite.exec("RELEASE translation_batch");
        throw error;
      }
    },
  };
  const env = {
    DB: db, READER_V1: "1", READER_TRANSLATIONS: new TranslationKV(),
    READER_TRANSLATE_QUEUE: {
      async send(body: { jobId: string; generation: number }, options?: { delaySeconds: number }) {
        queue.push(body);
        delays.push(options?.delaySeconds);
      },
    },
    NEWS_SENTRY_ENVIRONMENT: "dev", MAGPIE_BASE_URL: "http://localhost:3425",
    MAGPIE_FREE_ONLY: "1", MAGPIE_FREE_GROUP: "group/reader-free",
    ...extra,
  } as unknown as ReaderTranslationJobsEnv;
  return { env, queue, delays, sqlite };
}
