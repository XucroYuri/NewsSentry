export type PublicReadDatabase = Pick<D1Database, "prepare" | "batch">;

type SessionCapableD1 = D1Database & {
  withSession?: (constraint: "first-unconstrained") => PublicReadDatabase;
};

export function createPublicReadSession(db: D1Database): PublicReadDatabase {
  const maybeSession = db as SessionCapableD1;
  if (typeof maybeSession.withSession === "function") {
    return maybeSession.withSession("first-unconstrained");
  }
  return db;
}
