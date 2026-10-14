// Frekno website: settings, data loading, search, results list and spot panel.
import { loadTile, slots, spot } from "./frk.js";
import { CLASSES, layerLevels, makeContext, rank, score, sourceSpectrum, tolerated } from "./model.js";
import { applyStatic, dir, lang, num, setLang, t } from "./i18n.js";
import { SCORE_COLORS, createMap, inCzechia, setBasemap, setSelected, setSpots, setTiles, viewBbox } from "./map.js";
import { clock, hasStop, indexStops, nearestStop } from "./transit.js";

const DATA = "data/";
const MAX_VIEW_TILES = 24, MAX_LIST = 100, MAX_MAP = 20000, CACHE_TILES = 40, PARALLEL = 6;
const TIERS = { inaudible: 27, cz35: 35, night45: 45 };
const PROTECT = { flag: 0, strict: 5, all: 127 };
const ACCESS = { any: null, track100: { kind: "track", max: 100 }, track300: { kind: "track", max: 300 },
  road300: { kind: "road", max: 300 }, road1000: { kind: "road", max: 1000 } };
const TRANSIT = { any: null, stop1000: { max: 1000, night: false }, stop2000: { max: 2000, night: false },
  stop5000: { max: 5000, night: false }, night2000: { max: 2000, night: true }, night5000: { max: 5000, night: true } };
const LAYER_KEYS = ["home", "cottage", "campsite", "care", "recreation"];
const AREAS = { all: "cz", de: "de-leipzig" }; // area button -> the "area" of its tiles in index.json
const REF_RIG = { cls: "medium", character: "very_bass_heavy" }; // the screening's reference rig behind ref_min_dba
const DEFAULTS = { cls: "medium", character: "very_bass_heavy", level: 99, distance: 20, cardioid: false, tier: "night45", goal: 40,
  perLayer: false, lt: [40, 40, 40, 40, 40], layers: [1, 1, 0, 0, 0], sites: [0, 1, 2], flat: 0, access: "any", transit: "any",
  protect: "flag", forestLaw: false, smin: 1, smax: 10, area: "view", view: null, base: "night" };
const CHOICES = { cls: ["small", "medium", "large", "custom"], character: ["balanced", "bass_heavy", "very_bass_heavy"],
  tier: ["inaudible", "cz35", "night45", "custom"], access: Object.keys(ACCESS), transit: Object.keys(TRANSIT), protect: Object.keys(PROTECT),
  area: ["view", "all", "de"], base: ["night", "topo", "orto"], flat: [0, 2000, 5000, 10000, 20000] };

const $ = (s) => document.querySelector(s);
const form = $("#controls");
const field = (n) => form.elements.namedItem(n);
const state = readHash();
const cache = new Map();
let index = null, api = null, results = [], metaById = new Map(), gen = 0, selected = null, prot = null, timer = 0;
let status = ["", {}], nearBorder = false, nearMilitary = false, stopsP = null;

function readHash() {
  const s = structuredClone(DEFAULTS);
  for (const [k, v] of new URLSearchParams(location.hash.slice(1))) {
    if (!(k in s)) continue;
    const d = DEFAULTS[k];
    if (Array.isArray(d) || d === null) s[k] = v === "" ? [] : v.split(",").map(Number);
    else if (typeof d === "number") s[k] = Number(v) || d;
    else if (typeof d === "boolean") s[k] = v === "1";
    else s[k] = v;
  }
  for (const [k, list] of Object.entries(CHOICES)) if (!list.includes(s[k])) s[k] = DEFAULTS[k];
  for (const k of ["layers", "lt"]) if (s[k].length !== 5 || !s[k].every(Number.isFinite)) s[k] = DEFAULTS[k].slice();
  s.sites = s.sites.filter((v) => [0, 1, 2].includes(v));
  s.smin = Math.min(10, Math.max(1, Math.round(s.smin)));
  s.smax = Math.min(10, Math.max(s.smin, Math.round(s.smax)));
  if (s.view && (s.view.length !== 3 || !s.view.every(Number.isFinite))) s.view = null;
  return s;
}

function writeHash() {
  const p = new URLSearchParams();
  for (const [k, d] of Object.entries(DEFAULTS)) {
    const v = state[k];
    if (JSON.stringify(v) === JSON.stringify(d)) continue;
    p.set(k, Array.isArray(v) ? v.join(",") : typeof v === "boolean" ? (v ? "1" : "0") : String(v));
  }
  const h = p.toString();
  history.replaceState(null, "", h ? `#${h}` : location.pathname + location.search);
}

const clamp = (v, lo, hi, d) => (Number.isFinite(Number(v)) && v !== "" ? Math.min(hi, Math.max(lo, Number(v))) : d);

function fillForm() {
  for (const k of ["cls", "character", "access", "transit", "protect", "tier"]) field(k).value = state[k];
  for (const k of ["level", "distance", "goal", "flat", "smin", "smax"]) field(k).value = String(state[k]);
  for (const k of ["cardioid", "perLayer", "forestLaw"]) field(k).checked = state[k];
  form.querySelectorAll("[name=layer]").forEach((el, l) => { el.checked = Boolean(state.layers[l]); });
  form.querySelectorAll(".lt").forEach((el, l) => { el.value = String(state.lt[l]); });
  form.querySelectorAll("[name=site]").forEach((el) => { el.checked = state.sites.includes(Number(el.value)); });
}

function readForm() {
  for (const k of ["cls", "character", "access", "transit", "protect", "tier"]) state[k] = field(k).value;
  state.level = clamp(field("level").value, 60, 140, 99);
  state.distance = clamp(field("distance").value, 1, 200, 20);
  state.goal = clamp(field("goal").value, 15, 70, 40);
  state.flat = Number(field("flat").value);
  state.smin = Number(field("smin").value);
  state.smax = Math.max(state.smin, Number(field("smax").value));
  field("smax").value = String(state.smax);
  for (const k of ["cardioid", "perLayer", "forestLaw"]) state[k] = field(k).checked;
  state.layers = [...form.querySelectorAll("[name=layer]")].map((el) => (el.checked ? 1 : 0));
  state.lt = [...form.querySelectorAll(".lt")].map((el) => clamp(el.value, 15, 70, 40));
  state.sites = [...form.querySelectorAll("[name=site]:checked")].map((el) => Number(el.value));
}

function showModes() {
  form.dataset.cls = state.cls;
  form.dataset.tier = state.tier;
  form.dataset.perLayer = state.tier === "custom" && state.perLayer ? "1" : "0";
  $("#tier-note").textContent = t(`note_${state.tier}`);
  document.querySelectorAll("[data-area]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.area === state.area)));
  legend();
  document.querySelectorAll("[data-base]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.base === state.base)));
  document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang())));
  const mb = index && state.area !== "view" ? areaTiles().reduce((a, m) => a + m.bytes, 0) / 1e6 : 0;
  $("#area-note").textContent = state.area !== "view" ? t("all_size", { mb: num(mb) }) : "";
}

// Tiles of the chosen area button (all of Czechia or the Leipzig area).
const areaTiles = () => index.tiles.filter((m) => (m.area ?? "cz") === AREAS[state.area]);
const czView = () => { const c = api.map.getCenter(); return inCzechia(c.lng, c.lat); };

// Show the chosen area: the Leipzig area always, all of Czechia when none of it is in view.
function fitArea() {
  const metas = areaTiles();
  if (!metas.length || (state.area === "all" && metas.some((m) => intersects(m.bbox, viewBbox(api.map))))) return;
  const b = metas.reduce((a, m) => [Math.min(a[0], m.bbox[0]), Math.min(a[1], m.bbox[1]), Math.max(a[2], m.bbox[2]), Math.max(a[3], m.bbox[3])], [180, 90, -180, -90]);
  api.map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 20 });
}

const opts = () => ({
  cardioid: state.cardioid, layers: state.layers.map(Boolean),
  targets: state.tier !== "custom" ? Array(5).fill(TIERS[state.tier]) : state.perLayer ? state.lt.slice() : Array(5).fill(state.goal),
});
const rig = (cls = state.cls) => (cls === "custom" ? { cls, character: state.character, level: state.level, distance: state.distance }
  : { cls, character: state.character });
const intersects = (a, b) => a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];

function getTile(meta) {
  let p = cache.get(meta.id);
  if (!p) p = loadTile(DATA + meta.file).catch((e) => { cache.delete(meta.id); throw e; });
  cache.delete(meta.id);
  cache.set(meta.id, p);
  while (cache.size > CACHE_TILES) cache.delete(cache.keys().next().value);
  return p;
}

// Load the tiles of *metas* a few at a time and hand each to onTile(meta, tile) as soon as it arrives.
async function eachTile(metas, onTile, progress) {
  let next = 0, done = 0;
  const worker = async () => {
    while (next < metas.length) {
      const m = metas[next++];
      onTile(m, await getTile(m));
      progress(++done, metas.length);
    }
  };
  await Promise.all(Array.from({ length: Math.min(PARALLEL, metas.length) }, worker));
}

// Best margin first; ties in tile and spot order.
const byMargin = (a, b) => b.margin - a.margin || (a.tile < b.tile ? -1 : a.tile > b.tile ? 1 : a.i - b.i);

// A ranked spot with what the list and the map need, so the tile itself can leave memory.
function keep(id, tile, r) {
  const s = spot(tile, r.i);
  const s0 = r.layer >= 0 ? slots(tile, r.i, r.layer)[0] : { dist: 0, brg: 0 };
  return { ...r, tile: id, lon: s.lon, lat: s.lat, prot: s.prot, d0: s0.dist, b0: s0.brg };
}

function schedule(ms = 120) {
  clearTimeout(timer);
  timer = setTimeout(search, ms);
}

// Tile colours for the overview: the best spot of each tile for the reference rig, shifted to the chosen rig.
function overview() {
  const a = index.model.a_weighting_db;
  const level = (src) => 10 * Math.log10(src.reduce((e, v, b) => e + 10 ** ((v + a[b]) / 10), 0));
  const shift = level(sourceSpectrum(index, rig())) - level(sourceSpectrum(index, REF_RIG));
  const o = opts();
  const target = Math.min(...o.targets.filter((_, l) => o.layers[l]));
  setTiles(api.map, index.tiles.map((m) => {
    const s = m.spots === 0 ? 0 : m.ref_min_dba === null ? 10 : score(target - m.ref_min_dba - shift);
    return { bbox: m.bbox, outline: m.outline, s: s < state.smin ? 0 : s };
  }));
}

// Sites near the state border are left out of the data; say so when the area touches them.
function noteBorder() {
  $("#border-note").textContent = [nearBorder && t("border_hidden"), nearMilitary && t("military_hidden")].filter(Boolean).join(" ");
}

async function search() {
  const my = ++gen;
  showModes();
  writeHash();
  overview();
  const bbox = state.area === "view" ? viewBbox(api.map) : null;
  const metas = bbox ? index.tiles.filter((m) => intersects(m.bbox, bbox)) : areaTiles();
  nearBorder = metas.some((m) => m.border_dropped > 0);
  nearMilitary = metas.some((m) => m.military_dropped > 0);
  noteBorder();
  const load = metas.filter((m) => m.spots > 0);
  if (state.area === "view" && load.length > MAX_VIEW_TILES) return show([], "zoom_hint");
  const ctx = makeContext(index, rig(), opts());
  const f = {
    sites: state.sites, minFlat: state.flat, access: ACCESS[state.access] ?? null,
    excludeProt: (PROTECT[state.protect] ?? 0) | (index.border_bit ?? 128), forestLaw: state.forestLaw,
    bbox,
  };
  let best = [], total = 0;
  try {
    const tr = TRANSIT[state.transit];
    if (tr) {
      const st = await getStops();
      f.near = (x, y) => hasStop(st, x, y, tr.max, tr.night);
    }
    if (my !== gen) return;
    await eachTile(load, (m, tile) => {
      if (my !== gen) return;
      const part = rank([{ id: m.id, t: tile }], ctx, f).filter((r) => r.score >= state.smin && r.score <= state.smax).map((r) => keep(m.id, tile, r));
      total += part.length;
      best = best.concat(part);
      if (best.length > 2 * MAX_MAP) best = best.sort(byMargin).slice(0, MAX_MAP);
    }, (d, n) => { if (my === gen && d < n) $("#status").textContent = t("loading", { done: d, total: n }); });
  } catch (e) {
    if (my === gen) show([], "load_error", { msg: e.message });
    return;
  }
  if (my !== gen) return;
  best = best.sort(byMargin).slice(0, MAX_MAP);
  show(best, total ? "count" : "empty", { n: num(total, 0), shown: Math.min(total, MAX_LIST) });
}

function show(all, key, vars = {}) {
  results = all;
  status = [key, vars];
  $("#status").textContent = key ? t(key, vars) : "";
  setSpots(api.map, all.slice(0, MAX_MAP).map((r, k) => ({ lon: r.lon, lat: r.lat, score: r.score, key: k })));
  $("#list").replaceChildren(...all.slice(0, MAX_LIST).map(listItem));
  const k = selected ? all.findIndex((r) => r.tile === selected.tile && r.i === selected.i) : -1;
  if (k >= 0) openPanel(k, false);
  else closePanel();
}

const km = (m) => num(m / 1000);
const deg = (brg) => (brg * 360) / 256;
const marginText = (r) => (r.margin === Infinity ? t("nobody") : t(r.margin >= 0 ? "below" : "above", { m: num(Math.abs(r.margin)) }));
const ink = (sc) => ([1, 2, 6].includes(sc) ? "#ffffff" : "#0f1c24");
const badge = (sc) => `<span class="score" style="--c:${SCORE_COLORS[sc - 1]};--t:${ink(sc)}">${sc}</span>`;

function loudestText(r) {
  if (r.layer < 0) return "";
  const text = t("at_loudest", { l: num(r.level), layer: t(`layer_${LAYER_KEYS[r.layer]}`).toLowerCase(), d: km(r.d0), dir: dir(deg(r.b0)) });
  return text;
}

function listItem(r, k) {
  const li = document.createElement("li");
  const b = document.createElement("button");
  b.type = "button";
  b.className = "hit";
  b.innerHTML = `${badge(r.score)}<span class="what"><b>${marginText(r)}</b><span>${loudestText(r)}</span></span>`;
  b.addEventListener("click", () => openPanel(k, true));
  li.append(b);
  return li;
}

const meters = (m) => (m >= 5000 ? "> 5 km" : m >= 1000 ? `${num(m / 1000)} km` : `${m} m`);

async function protectedNames(ids) {
  if (!prot) prot = fetch(DATA + index.protected_file).then((r) => r.json());
  const p = await prot;
  return ids.map((j) => (p.sites[j][0].startsWith("DE-") ? p.sites[j][2] : `${t(`cat_${p.sites[j][1]}`)} ${p.sites[j][2]}`)).join(", ");
}

function getStops() {
  if (!stopsP) {
    stopsP = fetch(DATA + "stops.json").then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status} for stops.json`);
      return res.json();
    }).then(indexStops).catch((e) => { stopsP = null; throw e; });
  }
  return stopsP;
}

const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// A stop ({ s, d } from nearestStop) with its departures on the two weekend nights, as list items.
function stopRows(st, n, key) {
  const cs = lang() === "cs";
  const day = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(cs ? "cs-CZ" : "en-GB", { day: "numeric", month: cs ? "numeric" : "short" });
  const nights = [0, 1].map((j) => {
    const last = clock(n.s[3 + 2 * j]), first = clock(n.s[4 + 2 * j]);
    return `<li>${t(`night_${j}`, { d: day(st.nights[j]) })}: ${last ? t("after", { t: last }) : t("after_none")}, ${first ? t("morning", { t: first }) : t("morning_none")}</li>`;
  });
  return `<li>${t(key, { name: esc(n.s[2]), d: km(n.d) })}</li>${nights.join("")}`;
}

// The spot's nearest stop and, when nothing leaves it after midnight, the nearest stop that has such a departure.
function transitRows(st, s) {
  const n = nearestStop(st, s.x, s.y, 20000);
  if (!n) return `<li>${t("stop_none")}</li>`;
  const late = n.s[3] < 0 && n.s[5] < 0 ? nearestStop(st, s.x, s.y, 20000, true) : null;
  return stopRows(st, n, "stop_near") + (late ? stopRows(st, late, "stop_night") : "");
}

async function openPanel(k, fly) {
  const r = results[k];
  if (!r) return;
  selected = { tile: r.tile, i: r.i };
  const tile = await getTile(metaById.get(r.tile));
  if (results[k] !== r) return;
  const s = spot(tile, r.i), o = opts();
  const cz = (metaById.get(r.tile)?.area ?? "cz") === "cz";
  setSelected(api.map, s);
  if (fly) api.map.flyTo({ center: [s.lon, s.lat], zoom: Math.max(api.map.getZoom(), 13) });
  const lv = layerLevels(tile, r.i, makeContext(index, rig(), o), r.facing);
  const tol = tolerated(tile, r.i, Object.fromEntries(CLASSES.map((c) => [c, makeContext(index, rig(c), o)])));
  const cl = tol.largest ? index.model.classes[tol.largest] : null;
  const rows = LAYER_KEYS.map((key, l) => {
    const sl = slots(tile, r.i, l);
    if (!o.layers[l] || sl.length === 0) return "";
    return `<li><b>${t(`layer_${key}`)}</b> ${t("layer_row", { l: num(lv[l]), d: km(sl[0].dist), dir: dir(deg(sl[0].brg)) })}</li>`;
  }).join("");
  const facts = [
    t("site_type", { type: t(`site_${s.site}`), forest: s.forest }),
    t("slope", { slope: s.slope === 255 ? t("unknown") : s.slope, flat: num(s.flat / 10000) }),
    t("dist", { road: meters(s.roadM), track: meters(s.trackM), forest: meters(s.forestM) }),
  ];
  if (cz && s.forestM <= 50) facts.push(t("forest_flag")); // Czech forest law only
  const meter = Array.from({ length: 10 }, (_, j) => `<i class="${j < r.score ? "on" : ""}${j === 5 ? " goal" : ""}"></i>`).join("");
  const el = $("#panel");
  el.innerHTML = `<button type="button" class="x" aria-label="${t("close")}">×</button>
    <div class="meter" style="--c:${SCORE_COLORS[r.score - 1]}">${meter}</div>
    <p class="big">${badge(r.score)}<span><b>${t("score_of", { s: r.score })}</b> ${marginText(r)}</span></p>
    <p>${loudestText(r)}</p>
    ${r.facing !== null ? `<p>${t("facing", { deg: r.facing, dir: dir(r.facing) })}</p>` : ""}
    <p>${cl ? t("largest", { cls: t(`cls_${tol.largest}`).split(" (")[0], l: num(cl.level_dba + tol.margins[tol.largest]), d: cl.distance_m }) : t("largest_none")}</p>
    ${state.cls === "custom" && r.margin !== Infinity ? `<p>${t("yours", { l: num(state.level + r.margin), d: state.distance })}</p>` : ""}
    <h3>${t("loudest")}</h3><ul>${rows}</ul>
    <h3>${t("site")}</h3><ul>${facts.map((f) => `<li>${f}</li>`).join("")}<li class="prot"></li></ul>
    <h3>${t("transit")}</h3><ul class="transit"><li>${t("stop_loading")}</li></ul>
    <p class="links">${cz ? `<a href="https://nahlizenidokn.cuzk.gov.cz/MapaIdentifikace.aspx?l=KN&amp;x=${s.x}&amp;y=${s.y}" target="_blank" rel="noopener">${t("owner")}</a>` : ""}
    <a href="https://mapy.cz/zakladni?source=coor&amp;id=${s.lon.toFixed(5)}%2C${s.lat.toFixed(5)}&amp;x=${s.lon.toFixed(5)}&amp;y=${s.lat.toFixed(5)}&amp;z=16" target="_blank" rel="noopener">${t("mapy")}</a></p>
    <p class="note">${t(cz ? "owner_note" : "owner_de")}</p>
    <p class="coords">${num(s.lat, 5)} N, ${num(s.lon, 5)} E</p>`;
  el.hidden = false;
  el.querySelector(".x").addEventListener("click", () => { selected = null; closePanel(); });
  const li = el.querySelector(".prot");
  li.textContent = s.sites.length ? "" : t("prot_none");
  if (s.sites.length) li.textContent = t("prot_list", { names: await protectedNames(s.sites) });
  const tl = el.querySelector(".transit");
  try {
    tl.innerHTML = transitRows(await getStops(), s);
  } catch {
    tl.innerHTML = `<li>${t("stop_error")}</li>`;
  }
}

function closePanel() {
  $("#panel").hidden = true;
  if (api) setSelected(api.map, null);
}

function legend() {
  const off = (sc) => (sc < state.smin || sc > state.smax ? ' class="off"' : "");
  $("#legend").title = t("legend_click");
  $("#legend").innerHTML = `<span>${t("legend_over")}</span>${SCORE_COLORS.map((c, j) => `<i${off(j + 1)} data-s="${j + 1}" style="--c:${c};--t:${ink(j + 1)}">${j + 1}</i>`).join("")}<span>${t("legend_meet")}</span>`;
}

function setLanguage(code) {
  setLang(code);
  try { localStorage.setItem("frekno-lang", lang()); } catch { /* storage may be blocked */ }
  applyStatic(document);
  $("#about-body").innerHTML = t("about_html") + t("about_de_html");
  legend();
  noteBorder();
  showModes();
  if (api && index) show(results, ...status);
}

async function main() {
  let saved = null;
  try { saved = localStorage.getItem("frekno-lang"); } catch { /* storage may be blocked */ }
  setLanguage(saved ?? (/^(cs|sk)/.test(navigator.language || "") ? "cs" : "en"));
  fillForm();
  showModes();
  api = createMap($("#map"), (k) => openPanel(k, false));
  if (state.view) api.map.jumpTo({ center: [state.view[0], state.view[1]], zoom: state.view[2] });
  try {
    const res = await fetch(`${DATA}index.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    index = await res.json();
    metaById = new Map(index.tiles.map((m) => [m.id, m]));
    if (!index.tiles.some((m) => m.area === AREAS.de)) {
      $('[data-area="de"]').hidden = true;
      if (state.area === "de") state.area = "view";
    }
  } catch (e) {
    status = ["load_error", { msg: e.message }];
    $("#status").textContent = t(...status);
    return;
  }
  await api.ready;
  if (!state.view && state.area !== "view") fitArea();
  setBasemap(api.map, state.base, czView());
  form.addEventListener("input", () => { readForm(); schedule(); });
  form.addEventListener("change", () => { readForm(); schedule(); });
  form.addEventListener("submit", (e) => e.preventDefault());
  api.map.on("moveend", () => {
    const c = api.map.getCenter();
    state.view = [Number(c.lng.toFixed(4)), Number(c.lat.toFixed(4)), Number(api.map.getZoom().toFixed(2))];
    setBasemap(api.map, state.base, czView());
    if (state.area === "view") schedule(250);
    else writeHash();
  });
  document.querySelectorAll("[data-area]").forEach((b) => b.addEventListener("click", () => {
    state.area = b.dataset.area;
    if (state.area !== "view") fitArea();
    schedule(0);
  }));
  $("#legend").addEventListener("click", (e) => {
    const k = Number(e.target.closest("[data-s]")?.dataset.s);
    if (!k) return;
    Object.assign(state, { smin: k === state.smin ? 1 : k, smax: 10 });
    fillForm();
    schedule(0);
  });
  document.querySelectorAll("[data-base]").forEach((b) => b.addEventListener("click", () => {
    state.base = b.dataset.base;
    setBasemap(api.map, state.base, czView());
    showModes();
    writeHash();
  }));
  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLanguage(b.dataset.lang)));
  $("#about-open").addEventListener("click", () => $("#about").showModal());
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") { selected = null; closePanel(); } });
  search();
}

main();