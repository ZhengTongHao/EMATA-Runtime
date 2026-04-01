import test from "node:test";
import assert from "node:assert/strict";

import {
  ASK_COMMAND_TIMEOUT_MS,
  ASK_TURN_TIMEOUT_MS,
  buildAskJobEventsUrl,
  buildAskJobStatusUrl,
  resolveApiBaseUrl,
} from "../lib/api.js";

test("resolveApiBaseUrl trims trailing whitespace and slash", () => {
  assert.equal(
    resolveApiBaseUrl({
      NEXT_PUBLIC_EMATA_API_BASE_URL: "http://127.0.0.1:8000 /",
    }),
    "http://127.0.0.1:8000",
  );
});

test("resolveApiBaseUrl falls back to localhost when env is empty", () => {
  assert.equal(resolveApiBaseUrl({}), "http://localhost:8000");
});

test("ask timeouts leave more room for real feishu round trips", () => {
  assert.equal(ASK_TURN_TIMEOUT_MS, 60000);
  assert.equal(ASK_COMMAND_TIMEOUT_MS, 120000);
});

test("ask job helper builds status and events urls", () => {
  assert.equal(
    buildAskJobStatusUrl("job_123"),
    "http://localhost:8000/api/v1/ask/jobs/job_123",
  );
  assert.equal(
    buildAskJobEventsUrl("job_123"),
    "http://localhost:8000/api/v1/ask/jobs/job_123/events",
  );
});
