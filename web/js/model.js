// Site acoustics model. Definition and reference values: tests/make_web_fixtures.py.
import { BANDS, LAYERS, NO_FLOOR, layerBase, spotBase } from "./frk.js";

export const FACINGS = Array.from({ length: 24 }, (_, j) => 15 * j);
export const CLASSES = ["small", "medium", "large"];

// Band levels at 1 m for rig {cls, character} or {cls: "custom", character, level (dB(A)), distance (m)}.
export function sourceSpectrum(index, rig) {
  const m = index.model;
  if (rig.cls !== "custom") return m.source_1m_db[rig.cls][rig.character].slice();
  const shape = m.characters[rig.character].bands_db;
  const a = m.a_weighting_db, alpha = m.alpha_db_per_km, d = rig.distance;
  let e = 0;
  for (let b = 0; b < BANDS; b++) e += 10 ** ((shape[b] + a[b]) / 10);
  const shift = rig.level - 10 * Math.log10(e);
  return shape.map((v, b) => v + shift + 20 * Math.log10(d) + alpha[b] * (d - 1) / 1000);
}

const angdist = (u, v) => Math.abs((((u - v + 180) % 360) + 360) % 360 - 180);

// Cardioid gain in dB for a facing (degrees) and a 45 degree sector of receptor bearings.
export function gainDb(facing, sector, rear) {
  const a0 = 45 * sector, a1 = a0 + 45;
  const d = facing >= a0 && facing <= a1 ? 0 : Math.min(angdist(facing, a0), angdist(facing, a1));
  const g = (1 + Math.cos((d * Math.PI) / 180)) / 2;
  return g > 1e-12 ? Math.max(20 * Math.log10(g), -rear) : -rear;
}

// Precomputed tables for one rig and options {cardioid, layers: [5 bool], targets: [5 dB(A)]}.
export function makeContext(index, rig, opts) {
  const m = index.model;
  const src = sourceSpectrum(index, rig);
  const table = new Float64Array(BANDS * 256);
  for (let b = 0; b < BANDS; b++) {
    for (let v = 0; v < 256; v++) table[b * 256 + v] = 10 ** ((src[b] - v * index.att_step_db + m.a_weighting_db[b]) / 10);
  }
  const gains = new Float64Array(FACINGS.length * 8);
  FACINGS.forEach((f, j) => {
    for (let s = 0; s < 8; s++) gains[j * 8 + s] = 10 ** (gainDb(f, s, m.cardioid.rear_rejection_db) / 10);
  });
  return {
    src, table, gains, sub: index.bands_hz.map((f) => m.cardioid.bands_hz.includes(f)),
    cardioid: Boolean(opts.cardioid), layers: opts.layers.map(Boolean), targets: opts.targets.slice(), floorStep: index.floor_step_db,
  };
}

// {margin, level, layer, facing} of spot i; margin is Infinity when no layer that is on has a receptor.
export function evaluate(t, i, ctx) {
  const u8 = t.u8, table = ctx.table, sub = ctx.sub;
  const parts = [];
  for (let l = 0; l < LAYERS; l++) {
    if (!ctx.layers[l]) continue;
    const lb = layerBase(i, l);
    const n = u8[lb];
    if (n === 0) continue;
    const top = new Float64Array(n), low = new Float64Array(n), sec = new Uint8Array(n);
    for (let k = 0; k < n; k++) {
      const o = lb + 2 + k * 12;
      let et = 0, el = 0;
      for (let b = 0; b < BANDS; b++) {
        const e = table[b * 256 + u8[o + b]];
        if (sub[b]) el += e;
        else et += e;
      }
      top[k] = et;
      low[k] = el;
      sec[k] = u8[o + 11] >> 5;
    }
    const floor = u8[lb + 1];
    const floorLevel = floor === NO_FLOOR ? -Infinity : 10 * Math.log10(top[0] + low[0]) - floor * ctx.floorStep;
    parts.push({ l, n, top, low, sec, floorLevel });
  }
  if (parts.length === 0) return { margin: Infinity, level: -Infinity, layer: -1, facing: null };
  let best = null;
  const nf = ctx.cardioid ? FACINGS.length : 1;
  for (let j = 0; j < nf; j++) {
    let margin = Infinity, level = -Infinity, layer = -1;
    for (const p of parts) {
      let e = 0;
      for (let k = 0; k < p.n; k++) {
        const ek = ctx.cardioid ? p.top[k] + ctx.gains[j * 8 + p.sec[k]] * p.low[k] : p.top[k] + p.low[k];
        if (ek > e) e = ek;
      }
      const lev = Math.max(10 * Math.log10(e), p.floorLevel);
      if (ctx.targets[p.l] - lev < margin) {
        margin = ctx.targets[p.l] - lev;
        level = lev;
        layer = p.l;
      }
    }
    if (best === null || margin > best.margin + 1e-9) best = { margin, level, layer, facing: ctx.cardioid ? FACINGS[j] : null };
  }
  return best;
}

// Score 1..10 in 2.5 dB steps; 6 and above meet the target.
export const score = (margin) => (margin === Infinity ? 10 : Math.min(10, Math.max(1, 6 + Math.floor(margin / 2.5))));

// Filter f: {sites: [codes], minFlat, access: null | {kind: "track" | "road", max}, excludeProt (bits), forestLaw, bbox: null | [w, s, e, n],
// near: optional (x, y) => bool on the spot's S-JTSK position, checked last}.
export function passes(t, i, f) {
  const o = spotBase(i), u8 = t.u8, dv = t.dv;
  if (!f.sites.includes(u8[o + 16]) || dv.getUint16(o + 20, true) < f.minFlat) return false;
  if (f.access && dv.getUint16(o + (f.access.kind === "track" ? 26 : 24), true) > f.access.max) return false;
  if (u8[o + 19] & f.excludeProt || (f.forestLaw && dv.getUint16(o + 22, true) <= 50)) return false;
  const b = f.bbox;
  if (b) {
    const lon = dv.getFloat32(o, true), lat = dv.getFloat32(o + 4, true);
    if (lon < b[0] || lon > b[2] || lat < b[1] || lat > b[3]) return false;
  }
  return !f.near || f.near(dv.getInt32(o + 8, true), dv.getInt32(o + 12, true));
}

// Spots of tiles [{id, t}] that pass f, best margin first (ties keep tile and spot order), at most limit.
export function rank(tiles, ctx, f, limit = Infinity) {
  const out = [];
  for (const { id, t } of tiles) {
    for (let i = 0; i < t.count; i++) {
      if (!passes(t, i, f)) continue;
      const r = evaluate(t, i, ctx);
      out.push({ tile: id, i, margin: r.margin, level: r.level, layer: r.layer, facing: r.facing, score: score(r.margin) });
    }
  }
  out.sort((a, b) => b.margin - a.margin || 0);
  return out.length > limit ? out.slice(0, limit) : out;
}

// Margins of the preset classes (contexts {small, medium, large}) and the largest class that meets the targets.
export function tolerated(t, i, ctxs) {
  const margins = {};
  let largest = null;
  for (const cls of CLASSES) {
    margins[cls] = evaluate(t, i, ctxs[cls]).margin;
    if (margins[cls] >= 0) largest = cls;
  }
  return { margins, largest };
}

// Level of every layer of spot i (dB(A); -Infinity without receptors) at a facing from FACINGS, or omnidirectional (null).
export function layerLevels(t, i, ctx, facing = null) {
  const j = facing === null ? -1 : FACINGS.indexOf(facing);
  const out = [];
  for (let l = 0; l < LAYERS; l++) {
    const lb = layerBase(i, l);
    const n = t.u8[lb];
    let e = 0, e0 = 0;
    for (let k = 0; k < n; k++) {
      const o = lb + 2 + k * 12;
      let et = 0, el = 0;
      for (let b = 0; b < BANDS; b++) {
        const v = ctx.table[b * 256 + t.u8[o + b]];
        if (ctx.sub[b]) el += v;
        else et += v;
      }
      if (k === 0) e0 = et + el;
      const ek = j >= 0 ? et + ctx.gains[j * 8 + (t.u8[o + 11] >> 5)] * el : et + el;
      if (ek > e) e = ek;
    }
    const floor = t.u8[lb + 1];
    const floorLevel = n === 0 || floor === NO_FLOOR ? -Infinity : 10 * Math.log10(e0) - floor * ctx.floorStep;
    out.push(n === 0 ? -Infinity : Math.max(10 * Math.log10(e), floorLevel));
  }
  return out;
}
