import { PassThrough } from "node:stream";
import { test } from "node:test";
import assert from "node:assert/strict";

import { JsonlReader } from "../src/ipc/jsonl";

test("JsonlReader emits parsed messages", async () => {
  const stream = new PassThrough();
  const reader = new JsonlReader<{ a: number }>(stream);

  const messages: Array<{ a: number }> = [];
  reader.on("message", (msg) => messages.push(msg));

  stream.write('{"a":1}\n');
  stream.write('{"a":2}\n');
  stream.end();

  await new Promise<void>((resolve) => reader.on("end", () => resolve()));

  assert.deepEqual(messages, [{ a: 1 }, { a: 2 }]);
});

test("JsonlReader emits parse_error on invalid JSON", async () => {
  const stream = new PassThrough();
  const reader = new JsonlReader<unknown>(stream);

  const parseErrors: Array<{ line: string; err: unknown }> = [];
  reader.on("parse_error", (e) => parseErrors.push(e as any));

  stream.write("{not json}\n");
  stream.end();

  await new Promise<void>((resolve) => reader.on("end", () => resolve()));

  assert.equal(parseErrors.length, 1);
  assert.equal(parseErrors[0]?.line, "{not json}");
});

