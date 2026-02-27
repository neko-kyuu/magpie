import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import process from "node:process";

import { BackendClient } from "../src/ipc/backendClient";

function withEnv(vars: Record<string, string | undefined>, fn: () => Promise<void> | void) {
  const prev: Record<string, string | undefined> = {};
  for (const [k, v] of Object.entries(vars)) {
    prev[k] = process.env[k];
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  const res = fn();
  const restore = () => {
    for (const [k, v] of Object.entries(prev)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  };
  if (res && typeof (res as Promise<void>).then === "function") {
    return (res as Promise<void>).finally(restore);
  }
  restore();
  return res;
}

function waitForMessage(
  backend: BackendClient,
  predicate: (m: any) => boolean,
  timeoutMs = 2000
): Promise<any> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => {
      cleanup();
      reject(new Error("timeout waiting for message"));
    }, timeoutMs);

    const onMessage = (m: any) => {
      if (!predicate(m)) return;
      cleanup();
      resolve(m);
    };

    const cleanup = () => {
      clearTimeout(t);
      backend.off("message", onMessage);
    };

    backend.on("message", onMessage);
  });
}

async function findBufferedOrWait(
  backend: BackendClient,
  predicate: (m: any) => boolean,
  timeoutMs = 2000
) {
  const buffered = backend.consumeBufferedMessages();
  const hit = buffered.find(predicate);
  if (hit) return hit;
  return waitForMessage(backend, predicate, timeoutMs);
}

function mockBackendCmd() {
  const mock = path.resolve("fixtures/mock-backend.mjs");
  return `node ${JSON.stringify(mock)}`;
}

test("BackendClient buffers hello_ack after start()", async () => {
  await withEnv({ MAGPIE_BACKEND_CMD: mockBackendCmd(), MOCK_SEND_INVALID_JSON: undefined }, async () => {
    const backend = new BackendClient({ workspaceRoot: process.cwd(), permission: "ro" });
    await backend.start();
    const buffered = backend.consumeBufferedMessages();
    backend.stop();

    assert.ok(buffered.some((m: any) => m.type === "hello_ack"));
  });
});

test("BackendClient startQuery returns done for that request", async () => {
  await withEnv({ MAGPIE_BACKEND_CMD: mockBackendCmd(), MOCK_SEND_INVALID_JSON: undefined }, async () => {
    const backend = new BackendClient({ workspaceRoot: process.cwd(), permission: "ro" });
    await backend.start();

    const requestId = backend.startQuery("hello");
    const done = await waitForMessage(
      backend,
      (m) => m && m.type === "done" && m.in_reply_to === requestId
    );
    backend.stop();

    assert.equal(done.ok, true);
    assert.equal(done.canceled, false);
  });
});

test("BackendClient receives items for start request", async () => {
  await withEnv({ MAGPIE_BACKEND_CMD: mockBackendCmd(), MOCK_SEND_INVALID_JSON: undefined }, async () => {
    const backend = new BackendClient({ workspaceRoot: process.cwd(), permission: "ro" });
    await backend.start();

    const requestId = backend.startQuery("hello");
    const items = await waitForMessage(
      backend,
      (m) => m && m.type === "items" && m.in_reply_to === requestId
    );
    backend.stop();

    assert.equal(items.group, "rag");
    assert.equal(Array.isArray(items.items), true);
    assert.equal(items.items[0]?.id, "rag:1");
  });
});

test("BackendClient converts backend stderr to warn logs", async () => {
  await withEnv({ MAGPIE_BACKEND_CMD: mockBackendCmd(), MOCK_SEND_INVALID_JSON: undefined }, async () => {
    const backend = new BackendClient({ workspaceRoot: process.cwd(), permission: "ro" });
    await backend.start();

    const log = await findBufferedOrWait(
      backend,
      (m) => m && m.type === "log" && m.level === "warn" && String(m.message).includes("[backend stderr]")
    );
    backend.stop();

    assert.equal(log.type, "log");
  });
});

test("BackendClient logs parse_error on invalid JSONL from backend", async () => {
  await withEnv({ MAGPIE_BACKEND_CMD: mockBackendCmd(), MOCK_SEND_INVALID_JSON: "1" }, async () => {
    const backend = new BackendClient({ workspaceRoot: process.cwd(), permission: "ro" });
    await backend.start();

    const log = await findBufferedOrWait(
      backend,
      (m) => m && m.type === "log" && String(m.message).includes("failed to parse JSONL")
    );
    backend.stop();

    assert.equal(log.type, "log");
    assert.equal(log.level, "warn");
  });
});
