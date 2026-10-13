// Map: ČÚZK base maps (Web Mercator tile services), tile outlines, area rectangle, spots and the selected spot.
/* global maplibregl */
const AGS = "https://ags.cuzk.gov.cz/arcgis1/rest/services/";
export const SCORE_COLORS = ["#8e2622", "#c0392b", "#e05a2b", "#ee8d3a", "#f2c14e", "#1f7fb3", "#2fa4cf", "#5cc8e6", "#9fe6f5", "#e6fbff"];
const BASEMAPS = {
  night: { ztm: "visible", orto: "none", paint: { "raster-brightness-min": 0.42, "raster-brightness-max": 0.05, "raster-hue-rotate": 180, "raster-saturation": -0.8, "raster-contrast": 0 } },
  topo: { ztm: "visible", orto: "none", paint: { "raster-brightness-min": 0, "raster-brightness-max": 1, "raster-hue-rotate": 0, "raster-saturation": 0, "raster-contrast": 0 } },
  orto: { ztm: "none", orto: "visible", paint: null },
};
const EMPTY = { type: "FeatureCollection", features: [] };
const colorBy = ["match", ["get", "s"], ...SCORE_COLORS.flatMap((c, i) => [i + 1, c]), "#888"];

// Create the map in *container*; onSpot(key) fires when a spot is clicked. Returns {map, ready}.
export function createMap(container, onSpot) {
  const map = new maplibregl.Map({
    container, center: [15.4, 49.8], zoom: 6.6, minZoom: 6, maxZoom: 18, attributionControl: false,
    style: {
      version: 8,
      sources: {
        ztm: { type: "raster", tiles: [AGS + "ZTM_WM/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, minzoom: 6, maxzoom: 19, attribution: "© ČÚZK" },
        orto: { type: "raster", tiles: [AGS + "ORTOFOTO_WM/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, minzoom: 6, maxzoom: 20, attribution: "© ČÚZK" },
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": "#0d1a21" } },
        { id: "ztm", type: "raster", source: "ztm", paint: BASEMAPS.night.paint },
        { id: "orto", type: "raster", source: "orto", layout: { visibility: "none" } },
      ],
    },
  });
  map.addControl(new maplibregl.AttributionControl({ compact: true }));
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  const ready = new Promise((resolve) => map.on("load", () => {
    for (const id of ["tiles", "area", "spots", "sel"]) map.addSource(id, { type: "geojson", data: EMPTY });
    map.addLayer({ id: "tiles", type: "line", source: "tiles", paint: { "line-color": "#3a5c6b", "line-width": 0.7, "line-opacity": 0.7 } });
    map.addLayer({ id: "area-fill", type: "fill", source: "area", paint: { "fill-color": "#8fe3f0", "fill-opacity": 0.06 } });
    map.addLayer({ id: "area-line", type: "line", source: "area", paint: { "line-color": "#8fe3f0", "line-width": 1.5, "line-dasharray": [2, 2] } });
    map.addLayer({
      id: "glow", type: "circle", source: "spots", filter: [">=", ["get", "s"], 9],
      paint: { "circle-color": colorBy, "circle-blur": 1, "circle-opacity": 0.35,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4, 10, 8, 13, 18, 16, 30] },
    });
    map.addLayer({
      id: "spots", type: "circle", source: "spots", layout: { "circle-sort-key": ["get", "s"] },
      paint: { "circle-color": colorBy, "circle-stroke-color": "#0d1a21", "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 10, 0, 13, 0.8],
        "circle-opacity": ["case", [">=", ["get", "s"], 6], 1, 0.8],
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, ["case", [">=", ["get", "s"], 6], 1.8, 1], 10, ["case", [">=", ["get", "s"], 6], 3, 1.6],
          13, ["case", [">=", ["get", "s"], 6], 7, 4], 16, ["case", [">=", ["get", "s"], 6], 12, 8]] },
    });
    map.addLayer({ id: "sel", type: "circle", source: "sel", paint: { "circle-radius": 11, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
    map.on("click", "spots", (e) => onSpot(e.features[0].properties.k));
    map.on("mouseenter", "spots", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "spots", () => { map.getCanvas().style.cursor = ""; });
    resolve();
  }));
  return { map, ready };
}

const rect = (b) => ({ type: "Feature", properties: {}, geometry: { type: "Polygon",
  coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] } });

// Spots: [{lon, lat, score, key}].
export function setSpots(map, spots) {
  map.getSource("spots").setData({ type: "FeatureCollection", features: spots.map((p) => ({
    type: "Feature", properties: { s: p.score, k: p.key }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } })) });
}

export const setTiles = (map, tiles) => map.getSource("tiles").setData({ type: "FeatureCollection", features: tiles.map((t) => rect(t.bbox)) });
export const setArea = (map, bbox) => map.getSource("area").setData(bbox ? { type: "FeatureCollection", features: [rect(bbox)] } : EMPTY);
export const setSelected = (map, p) => map.getSource("sel").setData(p ? { type: "FeatureCollection", features: [{
  type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [p.lon, p.lat] } }] } : EMPTY);

export function setBasemap(map, mode) {
  const b = BASEMAPS[mode] ?? BASEMAPS.night;
  map.setLayoutProperty("ztm", "visibility", b.ztm);
  map.setLayoutProperty("orto", "visibility", b.orto);
  if (b.paint) for (const [k, v] of Object.entries(b.paint)) map.setPaintProperty("ztm", k, v);
}

// Current view as [west, south, east, north].
export function viewBbox(map) {
  const b = map.getBounds();
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
}

// Let the user click two corners; done([w, s, e, n]) or done(null) on Escape.
export function startDraw(map, done) {
  let first = null;
  const canvas = map.getCanvas();
  canvas.style.cursor = "crosshair";
  const box = (a, b) => [Math.min(a.lng, b.lng), Math.min(a.lat, b.lat), Math.max(a.lng, b.lng), Math.max(a.lat, b.lat)];
  const move = (e) => { if (first) setArea(map, box(first, e.lngLat)); };
  const finish = (bbox) => {
    map.off("click", click);
    map.off("mousemove", move);
    window.removeEventListener("keydown", key);
    canvas.style.cursor = "";
    done(bbox);
  };
  const click = (e) => {
    if (!first) first = e.lngLat;
    else finish(box(first, e.lngLat));
  };
  const key = (e) => { if (e.key === "Escape") finish(null); };
  map.on("click", click);
  map.on("mousemove", move);
  window.addEventListener("keydown", key);
}