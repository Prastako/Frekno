// Tests for web/js/map.js parts that need no browser: run with `node --test web/tests/map.test.mjs`.
import assert from "node:assert/strict";
import test from "node:test";
import { inCzechia } from "../js/map.js";

test("inCzechia tells Czech places from German and other neighbouring ones", () => {
  for (const [lon, lat] of [[14.42, 50.09], [16.61, 49.2], [18.26, 49.83], [12.37, 50.08], [14.47, 48.97]]) assert.equal(inCzechia(lon, lat), true, `${lon} ${lat}`);
  for (const [lon, lat] of [[12.37, 51.34], [13.74, 51.05], [13.0, 49.0], [17.11, 48.15], [19.94, 50.06], [16.37, 48.21]]) assert.equal(inCzechia(lon, lat), false, `${lon} ${lat}`);
});
