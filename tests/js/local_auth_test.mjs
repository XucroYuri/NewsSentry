import assert from "node:assert/strict";

globalThis.localStorage = {};
Object.defineProperty(globalThis, "navigator", {
  value: { language: "zh-CN", onLine: true },
  configurable: true,
});
globalThis.document = {
  body: {
    classList: {
      add() {},
      remove() {},
    },
  },
};
globalThis.window = {
  location: {
    origin: "http://127.0.0.1:8765",
    hash: "",
  },
  addEventListener() {},
};

const api = await import("../../src/news_sentry/static/api.js");

assert.equal(api.isLocalAppOrigin("http://127.0.0.1:8765"), true);
assert.equal(api.isLocalAppOrigin("http://localhost:8765"), true);
assert.equal(api.isLocalAppOrigin("http://[::1]:8765"), true);
assert.equal(api.isLocalAppOrigin("https://news.example.com"), false);
assert.equal(api.isAuthenticated(), true);
assert.equal(api.hasPermission("admin"), true);
assert.equal(api.getConnection().user, "local-admin");
