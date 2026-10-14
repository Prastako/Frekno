// Map: base maps (ČÚZK in Czechia; BKG TopPlusOpen and the states' orthophotos in Germany), tile outlines, spots and the selected spot.
/* global maplibregl */
const AGS = "https://ags.cuzk.gov.cz/arcgis1/rest/services/";
const TOPPLUS = "https://sgx.geodatenzentrum.de/wmts_topplus_open/tile/1.0.0/web/default/WEBMERCATOR/{z}/{y}/{x}.png";
const WMS = "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&STYLES=&CRS=EPSG:3857&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=TRUE&LAYERS=";
const DL_DE = '<a href="https://www.govdata.de/dl-de/by-2-0">dl-de/by-2-0</a>';
const DOP = { // orthophotos of the German states: WMS address, layer, bounds [west, south, east, north], attribution
  dop_sn: ["https://geodienste.sachsen.de/wms_geosn_dop-rgb/guest", "sn_dop_020", [11.87, 50.17, 15.04, 51.69], "© GeoSN"],
  dop_st: ["https://www.geodatenportal.sachsen-anhalt.de/wss/service/ST_LVermGeo_DOP_WMS_OpenData/guest", "lsa_lvermgeo_dop20_2", [10.56, 50.93, 13.19, 53.05], "© GeoBasis-DE / LVermGeo ST"],
  dop_th: ["https://www.geoproxy.geoportal-th.de/geoproxy/services/DOP", "th_dop", [9.87, 50.2, 12.66, 51.65], "© GDI-Th"],
  dop_bb: ["https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms", "bebb_dop20c", [11.26, 51.36, 14.77, 53.56], "© GeoBasis-DE/LGB"],
};
// Czechia's outline, coarse (lon, lat): the map centre decides which base maps are shown.
const CZ = [[12.05, 50.24], [12.09, 50.35], [12.21, 50.34], [12.31, 50.26], [12.49, 50.42], [12.82, 50.49], [12.95, 50.44], [13.0, 50.53],
  [13.17, 50.54], [13.22, 50.61], [13.35, 50.67], [13.45, 50.64], [13.53, 50.74], [13.83, 50.76], [13.88, 50.82], [14.31, 50.92], [14.22, 50.99],
  [14.29, 51.08], [14.53, 51.07], [14.69, 50.94], [14.67, 50.88], [14.77, 50.85], [14.82, 50.9], [14.95, 50.89], [14.96, 51.03], [15.18, 51.05],
  [15.31, 51.0], [15.32, 50.9], [15.41, 50.83], [15.72, 50.77], [15.83, 50.78], [15.9, 50.71], [15.98, 50.72], [16.05, 50.66], [16.23, 50.7],
  [16.37, 50.68], [16.49, 50.57], [16.27, 50.43], [16.39, 50.4], [16.66, 50.14], [16.97, 50.28], [16.82, 50.4], [16.89, 50.47], [17.22, 50.41],
  [17.28, 50.35], [17.37, 50.35], [17.45, 50.3], [17.62, 50.3], [17.67, 50.35], [17.74, 50.34], [17.8, 50.2], [17.67, 50.15], [17.82, 50.04],
  [17.9, 50.01], [18.04, 50.09], [18.32, 49.97], [18.6, 49.94], [18.67, 49.74], [18.85, 49.69], [18.89, 49.51], [18.76, 49.46], [18.59, 49.47],
  [18.41, 49.31], [18.23, 49.27], [18.13, 49.05], [18.07, 49.0], [17.96, 49.0], [17.91, 48.91], [17.53, 48.79], [17.46, 48.81], [17.35, 48.79],
  [17.21, 48.84], [16.95, 48.59], [16.88, 48.61], [16.87, 48.69], [16.67, 48.7], [16.64, 48.75], [16.48, 48.77], [16.38, 48.7], [16.09, 48.72],
  [15.81, 48.85], [15.68, 48.83], [15.35, 48.96], [15.15, 48.92], [15.11, 48.97], [15.04, 48.98], [15.02, 48.76], [14.96, 48.73], [14.85, 48.75],
  [14.73, 48.56], [14.48, 48.59], [14.33, 48.53], [14.04, 48.57], [13.97, 48.68], [13.79, 48.75], [13.71, 48.85], [13.55, 48.94], [13.49, 48.91],
  [13.4, 48.95], [13.31, 49.07], [13.15, 49.12], [12.95, 49.31], [12.77, 49.32], [12.62, 49.42], [12.48, 49.66], [12.36, 49.75], [12.49, 49.9],
  [12.23, 50.04], [12.16, 50.1], [12.16, 50.17]];
export const SCORE_COLORS = ["#8e2622", "#c0392b", "#e05a2b", "#ee8d3a", "#f2c14e", "#1f7fb3", "#2fa4cf", "#5cc8e6", "#9fe6f5", "#e6fbff"];
const NIGHT = { "raster-brightness-min": 0.42, "raster-brightness-max": 0.05, "raster-hue-rotate": 180, "raster-saturation": -0.8, "raster-contrast": 0 };
const DAY = { "raster-brightness-min": 0, "raster-brightness-max": 1, "raster-hue-rotate": 0, "raster-saturation": 0, "raster-contrast": 0 };
const EMPTY = { type: "FeatureCollection", features: [] };
const colorBy = ["match", ["get", "s"], ...SCORE_COLORS.flatMap((c, i) => [i + 1, c]), "#888"];

// Create the map in *container*; onSpot(key) fires when a spot is clicked. Returns {map, ready}.
export function createMap(container, onSpot) {
  const year = new Date().getFullYear();
  const map = new maplibregl.Map({
    container, center: [15.4, 49.8], zoom: 6.6, minZoom: 6, maxZoom: 18, attributionControl: false,
    style: {
      version: 8,
      sources: {
        ztm: { type: "raster", tiles: [AGS + "ZTM_WM/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, minzoom: 6, maxzoom: 19, attribution: "© ČÚZK" },
        orto: { type: "raster", tiles: [AGS + "ORTOFOTO_WM/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, minzoom: 6, maxzoom: 20, attribution: "© ČÚZK" },
        topplus: { type: "raster", tiles: [TOPPLUS], tileSize: 256, maxzoom: 18, attribution: `© <a href="https://www.bkg.bund.de">BKG</a> (${year}) ${DL_DE}, `
          + '<a href="https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/Datenquellen_TopPlusOpen.html">Datenquellen</a>' },
        ...Object.fromEntries(Object.entries(DOP).map(([id, [url, layer, bounds, attr]]) => [id,
          { type: "raster", tiles: [url + WMS + layer], tileSize: 256, bounds, maxzoom: 20, attribution: `${attr} ${DL_DE}` }])),
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": "#0d1a21" } },
        { id: "ztm", type: "raster", source: "ztm", paint: NIGHT },
        { id: "topplus", type: "raster", source: "topplus", layout: { visibility: "none" }, paint: NIGHT },
        { id: "orto", type: "raster", source: "orto", layout: { visibility: "none" } },
        ...Object.keys(DOP).map((id) => ({ id, type: "raster", source: id, layout: { visibility: "none" } })),
      ],
    },
  });
  map.addControl(new maplibregl.AttributionControl({ compact: true }));
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  const ready = new Promise((resolve) => map.on("load", () => {
    for (const id of ["tiles", "spots", "sel"]) map.addSource(id, { type: "geojson", data: EMPTY });
    map.addLayer({ id: "tiles-fill", type: "fill", source: "tiles", filter: [">", ["get", "s"], 0],
      paint: { "fill-color": colorBy, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 6, 0.35, 9, 0.12, 11, 0] } });
    map.addLayer({ id: "tiles", type: "line", source: "tiles", paint: { "line-color": "#3a5c6b", "line-width": 0.7, "line-opacity": 0.7 } });
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
const ring = (pts) => ({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[...pts, pts[0]]] } });

// Spots: [{lon, lat, score, key}].
export function setSpots(map, spots) {
  map.getSource("spots").setData({ type: "FeatureCollection", features: spots.map((p) => ({
    type: "Feature", properties: { s: p.score, k: p.key }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } })) });
}

// Tiles: [{bbox, outline, s}], outline = the tile's corners, s = overview score (0 = no fill).
export const setTiles = (map, tiles) => map.getSource("tiles").setData({ type: "FeatureCollection",
  features: tiles.map((t) => ({ ...(t.outline ? ring(t.outline) : rect(t.bbox)), properties: { s: t.s ?? 0 } })) });
export const setSelected = (map, p) => map.getSource("sel").setData(p ? { type: "FeatureCollection", features: [{
  type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [p.lon, p.lat] } }] } : EMPTY);

// True when (lon, lat) lies inside the coarse outline of Czechia.
export function inCzechia(lon, lat) {
  let inside = false;
  for (let i = 0, j = CZ.length - 1; i < CZ.length; j = i++) {
    const [xi, yi] = CZ[i], [xj, yj] = CZ[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// Base map *mode* (night, topo or orto): the ČÚZK maps when *cz*, else TopPlusOpen and the states' orthophotos.
export function setBasemap(map, mode, cz = true) {
  const orto = mode === "orto";
  const show = { ztm: !orto && cz, topplus: !orto && !cz, orto: orto && cz, ...Object.fromEntries(Object.keys(DOP).map((id) => [id, orto && !cz])) };
  for (const [id, on] of Object.entries(show)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  if (!orto) for (const id of ["ztm", "topplus"]) for (const [k, v] of Object.entries(mode === "topo" ? DAY : NIGHT)) map.setPaintProperty(id, k, v);
}

// Current view as [west, south, east, north].
export function viewBbox(map) {
  const b = map.getBounds();
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
}
