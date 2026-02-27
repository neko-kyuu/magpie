import { test } from "node:test";
import assert from "node:assert/strict";

import {
  RESULTS_GROUPS,
  cycleGroup,
  exitHistoryBrowse,
  firstNonEmptyGroup,
  historyDown,
  historyUp,
  initialHistoryState,
  normalizeSelection,
  pushHistory,
  wrapIndex,
  wrapSelection,
  type ResultsGroup,
} from "../src/ui/focus";

test("wrapIndex wraps for positive and negative", () => {
  assert.equal(wrapIndex(0, 3), 0);
  assert.equal(wrapIndex(3, 3), 0);
  assert.equal(wrapIndex(4, 3), 1);
  assert.equal(wrapIndex(-1, 3), 2);
});

test("wrapSelection wraps selection within list length", () => {
  assert.equal(wrapSelection(0, -1, 3), 2);
  assert.equal(wrapSelection(2, +1, 3), 0);
  assert.equal(wrapSelection(1, +1, 3), 2);
  assert.equal(wrapSelection(1, +10, 3), 2);
  assert.equal(wrapSelection(0, +1, 0), 0);
});

test("cycleGroup wraps in configured order", () => {
  const order = RESULTS_GROUPS;
  assert.deepEqual(order, ["web", "reddit", "clips"]);

  assert.equal(cycleGroup("web", +1), "reddit");
  assert.equal(cycleGroup("web", -1), "clips");
  assert.equal(cycleGroup("clips", +1), "web");
});

test("firstNonEmptyGroup selects the first group with items", () => {
  const lengths = { web: 0, reddit: 2, clips: 1 } satisfies Record<ResultsGroup, number>;
  assert.equal(firstNonEmptyGroup(lengths), "reddit");
  assert.equal(firstNonEmptyGroup({ web: 0, reddit: 0, clips: 0 }), null);
});

test("normalizeSelection resets out-of-range selections to 0", () => {
  assert.equal(normalizeSelection(0, 3), 0);
  assert.equal(normalizeSelection(2, 3), 2);
  assert.equal(normalizeSelection(-1, 3), 0);
  assert.equal(normalizeSelection(3, 3), 0);
  assert.equal(normalizeSelection(10, 0), 0);
});

test("historyUp/down browse entries and restores draft", () => {
  let hs = initialHistoryState();
  hs = pushHistory(hs, "first");
  hs = pushHistory(hs, "second");

  const up1 = historyUp(hs, "draft");
  hs = up1.state;
  assert.equal(up1.value, "second");

  const up2 = historyUp(hs, up1.value);
  hs = up2.state;
  assert.equal(up2.value, "first");

  const up3 = historyUp(hs, up2.value);
  hs = up3.state;
  assert.equal(up3.value, "first");

  const down1 = historyDown(hs, up3.value);
  hs = down1.state;
  assert.equal(down1.value, "second");

  const down2 = historyDown(hs, down1.value);
  hs = down2.state;
  assert.equal(down2.value, "draft");
  assert.equal(hs.browsingIndex, null);
});

test("exitHistoryBrowse clears browsingIndex", () => {
  let hs = initialHistoryState();
  hs = pushHistory(hs, "a");
  hs = historyUp(hs, "").state;
  assert.equal(hs.browsingIndex, 0);
  hs = exitHistoryBrowse(hs);
  assert.equal(hs.browsingIndex, null);
});

