import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { parseTile } from "../js/frk.js";
import { evaluate, gainDb, layerLevels, makeContext, passes, rank, score, sourceSpectrum, tolerated } from "../js/model.js";

const dir = new URL("./fixtures/", import.meta.url);
const index = JSON.parse(readFileSync(new URL("index.json", dir), "utf8"));
const exp = JSON.parse(readFileSync(new URL("expected.json", dir), "utf8"));
const raw = gunzipSync(readFileSync(new URL("tile.bin.gz", dir)));
const t = parseTile(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength));
const near = (a, e, tol = 1e-6) => Math.abs(a - e) <= tol;
const opts = (c) => ({ cardioid: c.cardioid, layers: c.layers.map(Boolean), targets: c.targets });
const ALL = { sites: [0, 1, 2], minFlat: 0, access: null, excludeProt: 0, forestLaw: false, bbox: null };

test("source spectra match", () => {
  for (const c of exp.cases) sourceSpectrum(index, c.rig).forEach((v, b) => assert.ok(near(v, c.source[b]), `${c.rig.cls} band ${b}`));
});

test("evaluate and score match the Python reference", () => {
  for (const c of exp.cases) {
    const ctx = makeContext(index, c.rig, opts(c));
    c.results.forEach((e, i) => {
      const r = evaluate(t, i, ctx);
      if (e.margin === null) {
        assert.deepEqual([r.margin, r.layer, r.facing], [Infinity, -1, null]);
      } else {
        assert.ok(near(r.margin, e.margin), `${c.rig.cls} spot ${i}: ${r.margin} vs ${e.margin}`);
        assert.ok(near(r.level, e.level));
        assert.deepEqual([r.layer, r.facing], [e.layer, e.facing]);
      }
      assert.equal(score(r.margin), e.score);
    });
  }
});

test("rank orders by margin and keeps ties in spot order", () => {
  for (const c of exp.cases) {
    const ctx = makeContext(index, c.rig, opts(c));
    assert.deepEqual(rank([{ id: "fixture", t }], ctx, ALL).map((x) => x.i), c.order);
    assert.deepEqual(rank([{ id: "fixture", t }], ctx, ALL, 3).map((x) => x.i), c.order.slice(0, 3));
  }
});

test("filters match", () => {
  for (const f of exp.filters) {
    const got = [];
    for (let i = 0; i < t.count; i++) if (passes(t, i, f)) got.push(i);
    assert.deepEqual(got, f.pass);
  }
});

test("tolerated gives class margins and the largest class that meets the target", () => {
  for (const c of exp.cases) {
    const ctxs = Object.fromEntries(["small", "medium", "large"].map((cls) => [cls, makeContext(index, { ...c.rig, cls }, opts(c))]));
    const r = tolerated(t, 3, ctxs);
    for (const cls of ["small", "medium", "large"]) assert.ok(near(r.margins[cls], c.reverse_spot3[cls]));
    const ok = ["small", "medium", "large"].filter((cls) => c.reverse_spot3[cls] >= 0);
    assert.equal(r.largest, ok.length ? ok[ok.length - 1] : null);
  }
});

test("cardioid gain", () => {
  assert.equal(gainDb(30, 0, 10), 0);
  assert.ok(near(gainDb(0, 2, 10), 20 * Math.log10(0.5)));
  assert.equal(gainDb(200, 0, 10), -10);
  assert.equal(gainDb(0, 7, 10), 0);
});

test("layer levels at the chosen facing give the same margin", () => {
  for (const c of exp.cases) {
    const ctx = makeContext(index, c.rig, opts(c));
    c.results.forEach((e, i) => {
      if (e.margin === null) return;
      const lv = layerLevels(t, i, ctx, e.facing);
      const m = Math.min(...lv.map((v, l) => (c.layers[l] ? c.targets[l] - v : Infinity)));
      assert.ok(near(m, e.margin), `${c.rig.cls} spot ${i}`);
    });
  }
});
