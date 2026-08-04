import { sanitizePublicSnapshotPayload } from "./snapshot-policy.ts";

const KV_SNAPSHOT_PREFIX = "k:";

export function kvSnapshotKey(snapshotKey: string): string {
  return `${KV_SNAPSHOT_PREFIX}${snapshotKey}`;
}

function snapshotEtag(payloadJson: string): string {
  return `"${payloadJson.length.toString(16)}"`;
}

export async function kvWriteSnapshot(
  kv: KVNamespace,
  snapshotKey: string,
  payload: unknown,
): Promise<void> {
  const sanitized = sanitizePublicSnapshotPayload(payload);
  await kv.put(kvSnapshotKey(snapshotKey), JSON.stringify(sanitized));
}

export async function kvReadSnapshot(
  kv: KVNamespace,
  snapshotKey: string,
): Promise<{ payload: unknown; etag: string } | null> {
  const raw = await kv.get(kvSnapshotKey(snapshotKey));
  if (raw === null) return null;
  return { payload: JSON.parse(raw), etag: snapshotEtag(raw) };
}
