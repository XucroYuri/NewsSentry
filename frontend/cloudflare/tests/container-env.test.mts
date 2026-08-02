import assert from "node:assert/strict";
import test from "node:test";

import { containerEnvVars } from "../workers/lib/container-env.ts";

test("container env disables full article fetches for production canary collection", () => {
  const envVars = containerEnvVars({});

  assert.equal(envVars.NEWSSENTRY_DEPLOYMENT_ENV, "cloudflare-container");
  assert.equal(envVars.NEWSSENTRY_AUTO_COLLECT, "0");
  assert.equal(envVars.NEWSSENTRY_FETCH_FULL_ARTICLE, "0");
});

