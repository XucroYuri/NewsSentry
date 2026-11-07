import {
  handleTranslationDlqBatch, handleTranslationQueueBatch, READER_TRANSLATE_CRON,
  READER_TRANSLATE_DLQ_NAME, READER_TRANSLATE_QUEUE_NAME, sweepTranslationJobs,
  type ReaderTranslationJobsEnv, type TranslationQueueBatch,
} from "./reader-translate-jobs.ts";

export async function dispatchReaderQueue(
  batch: TranslationQueueBatch, env: ReaderTranslationJobsEnv, shadow: () => Promise<void>,
): Promise<void> {
  if (batch.queue === "news-sentry-jobs" || batch.queue === "news-sentry-jobs-dlq") {
    await shadow();
  } else if (env.NEWS_SENTRY_ENVIRONMENT === "preview" && batch.queue === READER_TRANSLATE_QUEUE_NAME) {
    await handleTranslationQueueBatch(batch, env);
  } else if (env.NEWS_SENTRY_ENVIRONMENT === "preview" && batch.queue === READER_TRANSLATE_DLQ_NAME) {
    await handleTranslationDlqBatch(batch, env);
  } else {
    console.warn("unexpected queue ignored");
    for (const message of batch.messages) message.ack();
  }
}

export async function dispatchReaderSchedule(
  cron: string, env: ReaderTranslationJobsEnv, existing: () => Promise<unknown>,
): Promise<void> {
  if (env.NEWS_SENTRY_ENVIRONMENT === "preview" && cron === READER_TRANSLATE_CRON) {
    await sweepTranslationJobs(env);
  } else {
    await existing();
  }
}
