import { test } from "node:test";
import assert from "node:assert/strict";
import { clock, hasStop, indexStops, nearestStop } from "../js/transit.js";

const st = indexStops({ nights: ["2026-10-16", "2026-10-17", "2026-10-18"], stops: [
  [-740000, -1050000, "A", -1, 300, -1, 310],
  [-741500, -1050000, "B", 70, 280, -1, -1],
  [-745200, -1050000, "C", -1, -1, 30, 400],
] });

test("nearest stop and its distance", () => {
  const n = nearestStop(st, -740300, -1050400, 5000);
  assert.equal(n.s[2], "A");
  assert.equal(n.d, 500);
  assert.equal(nearestStop(st, -740300, -1050400, 400), null);
  assert.equal(nearestStop(st, -740300, -1050400, 5000, true).s[2], "B");
});

test("stop within a distance, with or without a departure after midnight", () => {
  assert.equal(hasStop(st, -740300, -1050400, 500), true);
  assert.equal(hasStop(st, -740300, -1050400, 499), false);
  assert.equal(hasStop(st, -740000, -1050000, 1000, true), false);
  assert.equal(hasStop(st, -740000, -1050000, 1500, true), true);
  assert.equal(hasStop(st, -749000, -1050000, 3700, true), false);
  assert.equal(hasStop(st, -749000, -1050000, 3800, true), true);
});

test("clock", () => {
  assert.equal(clock(-1), null);
  assert.equal(clock(0), "00:00");
  assert.equal(clock(70), "01:10");
  assert.equal(clock(719), "11:59");
});
