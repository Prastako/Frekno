import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { inflate, parseTile, spot, slots, layerBase } from "../js/frk.js";

const dir = new URL("./fixtures/", import.meta.url);
const exp = JSON.parse(readFileSync(new URL("expected.json", dir), "utf8"));
const gz = readFileSync(new URL("tile.bin.gz", dir));
const ab = (b) => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);

test("inflate gunzips and passes plain bytes through", async () => {
  const plain = ab(gunzipSync(gz));
  assert.deepEqual(new Uint8Array(await inflate(ab(gz))), new Uint8Array(plain));
  assert.equal(await inflate(plain), plain);
});

test("spot fields match the Python writer", async () => {
  const t = parseTile(await inflate(ab(gz)));
  assert.equal(t.count, exp.spots.length);
  exp.spots.forEach((e, i) => {
    const s = spot(t, i);
    for (const k of ["x", "y", "site", "forest", "slope", "prot", "flat", "forestM", "roadM", "trackM"]) assert.equal(s[k], e[k], `${k} of spot ${i}`);
    assert.ok(Math.abs(s.lon - e.lon) < 1e-9 && Math.abs(s.lat - e.lat) < 1e-9, `position of spot ${i}`);
    assert.deepEqual(s.sites, e.sites);
    for (let l = 0; l < 5; l++) {
      assert.equal(t.u8[layerBase(i, l)], e.n[l]);
      assert.equal(t.u8[layerBase(i, l) + 1], e.floor[l]);
      assert.equal(slots(t, i, l).length, e.n[l]);
    }
    const s1 = slots(t, i, 1);
    if (e.n[1] > 0) assert.deepEqual([s1[0].att, s1[0].dist, s1[0].brg], [e.att00, e.dist00, e.brg00]);
  });
});

test("bad header and truncated file are rejected", () => {
  const plain = new Uint8Array(ab(gunzipSync(gz)));
  const bad = plain.slice();
  bad[4] = 1;
  assert.throws(() => parseTile(bad.buffer));
  assert.throws(() => parseTile(plain.slice(0, 100).buffer));
});
