import { test } from "node:test";
import assert from "node:assert/strict";

import { newId } from "../src/ipc/ids";

test("newId returns a stable string id", () => {
  const id = newId();
  assert.equal(typeof id, "string");
  assert.ok(id.length > 0);

  const uuidLike =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const hexLike = /^[0-9a-f]{32}$/i;
  assert.ok(uuidLike.test(id) || hexLike.test(id));
});

