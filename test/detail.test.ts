import { test } from "node:test";
import assert from "node:assert/strict";

import { buildViewport, wrapLine, wrapText } from "../src/ui/detail";

test("wrapLine splits by width", () => {
  assert.deepEqual(wrapLine("", 3), [""]);
  assert.deepEqual(wrapLine("abc", 3), ["abc"]);
  assert.deepEqual(wrapLine("abcd", 3), ["abc", "d"]);
  assert.deepEqual(wrapLine("abcdef", 2), ["ab", "cd", "ef"]);
});

test("wrapText preserves newlines and wraps each line", () => {
  assert.deepEqual(wrapText("a\nbb\nccc", 2), ["a", "bb", "cc", "c"]);
});

test("buildViewport clamps offset and computes maxOffset", () => {
  const vp = buildViewport("abcdef", 2, 2, 10);
  assert.equal(vp.allLinesCount, 3);
  assert.equal(vp.maxOffset, 1);
  assert.equal(vp.offset, 1);
  assert.deepEqual(vp.lines, ["cd", "ef"]);
});

