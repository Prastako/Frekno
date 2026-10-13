// Public transport stops (data/stops.json from pipeline.transit): the nearest stop and its weekend departures.
// A stop is [x, y, name, night1, morning1, night2, morning2]: S-JTSK metres, then minutes after midnight (-1 = none).

const CELL = 1000;
const key = (cx, cy) => cx * 100000 + cy;

// The stops file with a grid of 1 km cells for nearest-stop lookups.
export function indexStops(data) {
  const grid = new Map();
  data.stops.forEach((s, i) => {
    const k = key(Math.floor(s[0] / CELL), Math.floor(s[1] / CELL));
    if (!grid.has(k)) grid.set(k, []);
    grid.get(k).push(i);
  });
  return { ...data, grid };
}

const night = (s) => s[3] >= 0 || s[5] >= 0;

// Nearest stop within max metres of (x, y) as { s, d }, or null; withNight = only stops with a departure after midnight.
export function nearestStop(st, x, y, max, withNight = false) {
  const cx = Math.floor(x / CELL), cy = Math.floor(y / CELL), r = Math.ceil(max / CELL);
  let best = null;
  for (let dx = -r; dx <= r; dx++) {
    for (let dy = -r; dy <= r; dy++) {
      const cell = st.grid.get(key(cx + dx, cy + dy));
      if (!cell) continue;
      for (const i of cell) {
        const s = st.stops[i];
        if (withNight && !night(s)) continue;
        const d = Math.hypot(s[0] - x, s[1] - y);
        if (d <= max && (!best || d < best.d)) best = { s, d };
      }
    }
  }
  return best;
}

// Whether a stop (with a departure after midnight if withNight) lies within max metres of (x, y).
export function hasStop(st, x, y, max, withNight = false) {
  const cx = Math.floor(x / CELL), cy = Math.floor(y / CELL), r = Math.ceil(max / CELL), m2 = max * max;
  for (let dx = -r; dx <= r; dx++) {
    for (let dy = -r; dy <= r; dy++) {
      const cell = st.grid.get(key(cx + dx, cy + dy));
      if (!cell) continue;
      for (const i of cell) {
        const s = st.stops[i];
        if ((!withNight || night(s)) && (s[0] - x) ** 2 + (s[1] - y) ** 2 <= m2) return true;
      }
    }
  }
  return false;
}

// "HH:MM" for minutes after midnight, null for -1.
export const clock = (m) => (m < 0 ? null : `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`);
