// Frekno website: settings, data loading, search, results list and spot panel.
import { loadTile, slots, spot } from "./frk.js";
import { CLASSES, layerLevels, makeContext, rank, tolerated } from "./model.js";
import { applyStatic, dir, lang, num, setLang, t } from "./i18n.js";
import { SCORE_COLORS, createMap, setArea, setBasemap, setSelected, setSpots, setTiles, startDraw, viewBbox } from "./map.js";

const DATA = "data/";
const MAX_VIEW_TILES = 24, MAX_LIST = 100, MAX_MAP = 20000, CACHE_TILES = 80, PARALLEL = 6;
const TIERS = { inaudible: 27, cz35: 35, night45: 45 };
const PROTECT = { flag: 0, strict: 5, all: 127 };
const ACCESS = { any: null, track100: { kind: "track", max: 100 }, track300: { kind: "track", max: 300 },
  road300: { kind: "road", max: 300 }, road1000: { kind: "road", max: 1000 } };
const LAYER_KEYS = ["home", "cottage", "campsite", "care", "recreation"];
const DEFAULTS = { cls: "medium", character: "very_bass_heavy", level: 99, distance: 20, cardioid: false, tier: "night45", goal: 40,
  perLayer: false, lt: [40, 40, 40, 40, 40], layers: [1, 1, 1, 1, 1], sites: [0, 1, 2], flat: 0, access: "any",
  protect: "flag", forestLaw: false, area: "view", rect: null, view: null, base: "night" };
const CHOICES = { cls: ["small", "medium", "large", "custom"], character: ["balanced", "bass_heavy", "very_bass_heavy"],
  tier: ["inaudible", "cz35", "night45", "custom"], access: Object.keys(ACCESS), protect: Object.keys(PROTECT),
  area: ["view", "rect", "all"], base: ["night", "topo", "orto"], flat: [0, 2000, 5000, 10000, 20000] };

const $ = (s) => document.querySelector(s);
const form = $("#controls");
const field = (n) => form.elements.namedItem(n);
const state = readHash();
const cache = new Map();
let index = null, api = null, results = [], byId = new Map(), gen = 0, drawing = false, selected = null, prot = null, timer = 0;
let status = ["", {}];

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
  if (s.rect && (s.rect.length !== 4 || !s.rect.every(Number.isFinite))) s.rect = null;
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
  for (const k of ["cls", "character", "access", "protect", "tier"]) field(k).value = state[k];
  for (const k of ["level", "distance", "goal", "flat"]) field(k).value = String(state[k]);
  for (const k of ["cardioid", "perLayer", "forestLaw"]) field(k).checked = state[k];
  form.querySelectorAll("[name=layer]").forEach((el, l) => { el.checked = Boolean(state.layers[l]); });
  form.querySelectorAll(".lt").forEach((el, l) => { el.value = String(state.lt[l]); });
  form.querySelectorAll("[name=site]").forEach((el) => { el.checked = state.sites.includes(Number(el.value)); });
}

function readForm() {
  for (const k of ["cls", "character", "access", "protect", "tier"]) state[k] = field(k).value;
  state.level = clamp(field("level").value, 60, 140, 99);
  state.distance = clamp(field("distance").value, 1, 200, 20);
  state.goal = clamp(field("goal").value, 15, 70, 40);
  state.flat = Number(field("flat").value);
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
  document.querySelectorAll("[data-base]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.base === state.base)));
  document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang())));
  const mb = index ? index.tiles.reduce((a, m) => a + m.bytes, 0) / 1e6 : 0;
  $("#area-note").textContent = drawing ? t("draw_hint") : state.area === "all" ? t("all_size", { mb: num(mb) }) : "";
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

async function loadAll(metas, progress) {
  const out = [];
  let next = 0, done = 0;
  const worker = async () => {
    while (next < metas.length) {
      const m = metas[next++];
      out.push({ id: m.id, t: await getTile(m) });
      progress(++done, metas.length);
    }
  };
  await Promise.all(Array.from({ length: Math.min(PARALLEL, metas.length) }, worker));
  return out.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

function schedule(ms = 120) {
  clearTimeout(timer);
  timer = setTimeout(search, ms);
}

async function search() {
  const my = ++gen;
  showModes();
  writeHash();
  let bbox = state.area === "view" ? viewBbox(api.map) : state.area === "rect" ? state.rect : null;
  setArea(api.map, state.area === "rect" ? state.rect : null);
  const metas = bbox ? index.tiles.filter((m) => intersects(m.bbox, bbox)) : index.tiles;
  if (state.area === "rect" && !bbox) return show([], "draw_hint");
  if (state.area === "view" && metas.length > MAX_VIEW_TILES) return show([], "zoom_hint");
  let tiles;
  try {
    tiles = await loadAll(metas, (d, n) => { if (my === gen && d < n) $("#status").textContent = t("loading", { done: d, total: n }); });
  } catch (e) {
    if (my === gen) show([], "load_error", { msg: e.message });
    return;
  }
  if (my !== gen) return;
  byId = new Map(tiles.map((x) => [x.id, x.t]));
  const all = rank(tiles, makeContext(index, rig(), opts()), {
    sites: state.sites, minFlat: state.flat, access: ACCESS[state.access] ?? null,
    excludeProt: PROTECT[state.protect] ?? 0, forestLaw: state.forestLaw, bbox: state.area === "all" ? null : bbox,
  });
  show(all, all.length ? "count" : "empty", { n: num(all.length, 0), shown: Math.min(all.length, MAX_LIST) });
}

function show(all, key, vars = {}) {
  results = all;
  status = [key, vars];
  $("#status").textContent = key ? t(key, vars) : "";
  setSpots(api.map, all.slice(0, MAX_MAP).map((r, k) => {
    const s = spot(byId.get(r.tile), r.i);
    return { lon: s.lon, lat: s.lat, score: r.score, key: k };
  }));
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
  const s0 = slots(byId.get(r.tile), r.i, r.layer)[0];
  return t("at_loudest", { l: num(r.level), layer: t(`layer_${LAYER_KEYS[r.layer]}`).toLowerCase(), d: km(s0.dist), dir: dir(deg(s0.brg)) });
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
  return ids.map((j) => `${t(`cat_${p.sites[j][1]}`)} ${p.sites[j][2]}`).join(", ");
}

async function openPanel(k, fly) {
  const r = results[k];
  if (!r) return;
  selected = { tile: r.tile, i: r.i };
  const tile = byId.get(r.tile), s = spot(tile, r.i), o = opts();
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
  if (s.forestM <= 50) facts.push(t("forest_flag"));
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
    <p class="links"><a href="https://nahlizenidokn.cuzk.gov.cz/MapaIdentifikace.aspx?l=KN&amp;x=${s.x}&amp;y=${s.y}" target="_blank" rel="noopener">${t("owner")}</a>
    <a href="https://mapy.cz/zakladni?source=coor&amp;id=${s.lon.toFixed(5)}%2C${s.lat.toFixed(5)}&amp;x=${s.lon.toFixed(5)}&amp;y=${s.lat.toFixed(5)}&amp;z=16" target="_blank" rel="noopener">${t("mapy")}</a></p>
    <p class="note">${t("owner_note")}</p>
    <p class="coords">${num(s.lat, 5)} N, ${num(s.lon, 5)} E</p>`;
  el.hidden = false;
  el.querySelector(".x").addEventListener("click", () => { selected = null; closePanel(); });
  const li = el.querySelector(".prot");
  li.textContent = s.sites.length ? "" : t("prot_none");
  if (s.sites.length) li.textContent = t("prot_list", { names: await protectedNames(s.sites) });
}

function closePanel() {
  $("#panel").hidden = true;
  if (api) setSelected(api.map, null);
}

function legend() {
  $("#legend").innerHTML = `<span>${t("legend_over")}</span>${SCORE_COLORS.map((c, j) => `<i style="--c:${c};--t:${ink(j + 1)}">${j + 1}</i>`).join("")}<span>${t("legend_meet")}</span>`;
}

function setLanguage(code) {
  setLang(code);
  try { localStorage.setItem("frekno-lang", lang()); } catch { /* storage may be blocked */ }
  applyStatic(document);
  $("#about-body").innerHTML = t("about_html");
  legend();
  showModes();
  if (api && index) show(results, ...status);
}

async function main() {
  let saved = null;
  try { saved = localStorage.getItem("frekno-lang"); } catch { /* storage may be blocked */ }
  setLanguage(saved ?? (/^(cs|sk)/.test(navigator.language || "") ? "cs" : "en"));
  fillForm();
  showModes();
  api = createMap($("#map"), (k) => { if (!drawing) openPanel(k, false); });
  if (state.view) api.map.jumpTo({ center: [state.view[0], state.view[1]], zoom: state.view[2] });
  try {
    const res = await fetch(`${DATA}index.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    index = await res.json();
  } catch (e) {
    status = ["load_error", { msg: e.message }];
    $("#status").textContent = t(...status);
    return;
  }
  await api.ready;
  setBasemap(api.map, state.base);
  setTiles(api.map, index.tiles);
  form.addEventListener("input", () => { readForm(); schedule(); });
  form.addEventListener("change", () => { readForm(); schedule(); });
  form.addEventListener("submit", (e) => e.preventDefault());
  api.map.on("moveend", () => {
    const c = api.map.getCenter();
    state.view = [Number(c.lng.toFixed(4)), Number(c.lat.toFixed(4)), Number(api.map.getZoom().toFixed(2))];
    if (state.area === "view") schedule(250);
    else writeHash();
  });
  document.querySelectorAll("[data-area]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.area !== "rect") {
      state.area = b.dataset.area;
      return schedule(0);
    }
    drawing = true;
    showModes();
    startDraw(api.map, (box) => {
      drawing = false;
      if (box) Object.assign(state, { area: "rect", rect: box.map((v) => Number(v.toFixed(4))) });
      schedule(0);
    });
  }));
  document.querySelectorAll("[data-base]").forEach((b) => b.addEventListener("click", () => {
    state.base = b.dataset.base;
    setBasemap(api.map, state.base);
    showModes();
    writeHash();
  }));
  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLanguage(b.dataset.lang)));
  $("#about-open").addEventListener("click", () => $("#about").showModal());
  window.addEventListener("keydown", (e) => { if (e.key === "Escape" && !drawing) { selected = null; closePanel(); } });
  search();
}

main();