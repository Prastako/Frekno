// Reader for Frekno tile files (format FRK1 version 2, written by pipeline/pack.py).
// A tile is a gzip file: 16-byte header, then one 406-byte record per spot (little-endian).

export const HEADER = 16;
export const SPOT = 406;
export const LAYERS = 5;
export const K = 6;
export const BANDS = 9;
export const LAYER = 2 + K * 12;
export const NO_SITE = 65535;
export const NO_FLOOR = 255;
const LAYER0 = 36;

// Return the bytes of *buf* (ArrayBuffer), gunzipped when they start with the gzip magic.
export async function inflate(buf) {
  const u8 = new Uint8Array(buf);
  if (u8[0] !== 0x1f || u8[1] !== 0x8b) return buf;
  const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
  return await new Response(stream).arrayBuffer();
}

// Check the header and wrap the records: {count, dv, u8}.
export function parseTile(buf) {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== "FRK1" || dv.getUint16(4, true) !== 2) throw new Error("not a FRK1 version 2 tile");
  if (dv.getUint8(6) !== LAYERS || dv.getUint8(7) !== K || dv.getUint8(8) !== BANDS) throw new Error("unexpected tile layout");
  const count = dv.getUint32(10, true);
  if (buf.byteLength < HEADER + count * SPOT) throw new Error("tile file is truncated");
  return { count, dv, u8: new Uint8Array(buf) };
}

export async function loadTile(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return parseTile(await inflate(await res.arrayBuffer()));
}

// Offset of spot i's record.
export const spotBase = (i) => HEADER + i * SPOT;
// Offset of layer l of spot i: n at +0, floor at +1, slots from +2.
export const layerBase = (i, l) => HEADER + i * SPOT + LAYER0 + l * LAYER;
// Offset of slot k of layer l of spot i: att[9] at +0, dist (uint16) at +9, bearing at +11.
export const slotBase = (i, l, k) => layerBase(i, l) + 2 + k * 12;

// All fields of spot i except the receptor slots.
export function spot(t, i) {
  const o = spotBase(i);
  const dv = t.dv;
  const sites = [];
  for (let j = 0; j < 4; j++) {
    const v = dv.getUint16(o + 28 + 2 * j, true);
    if (v !== NO_SITE) sites.push(v);
  }
  return {
    lon: dv.getFloat32(o, true), lat: dv.getFloat32(o + 4, true),
    x: dv.getInt32(o + 8, true), y: dv.getInt32(o + 12, true),
    site: t.u8[o + 16], forest: t.u8[o + 17], slope: t.u8[o + 18], prot: t.u8[o + 19],
    flat: dv.getUint16(o + 20, true), forestM: dv.getUint16(o + 22, true),
    roadM: dv.getUint16(o + 24, true), trackM: dv.getUint16(o + 26, true), sites,
  };
}

// Receptor slots of layer l of spot i: [{att: [9 uint8], dist, brg}], loudest first.
export function slots(t, i, l) {
  const n = t.u8[layerBase(i, l)];
  const out = [];
  for (let k = 0; k < n; k++) {
    const o = slotBase(i, l, k);
    out.push({ att: Array.from(t.u8.subarray(o, o + BANDS)), dist: t.dv.getUint16(o + 9, true), brg: t.u8[o + 11] });
  }
  return out;
}
