/* Breakup Watch Canada - user view (data from scripts/62_export_watch.py).
   Hay River = real data. Every other site = SIMULATED example (made up here, clearly labelled). */
(function () {
  "use strict";
  const W = window.HRFW.watch;
  const COLOR = { Safe: "#2e7d4f", Possible: "#f2b705", "High danger": "#eb2d37", None: "#9aa5b1" };
  const ICON = { Safe: "✓", Possible: "⚠", "High danger": "⛔", None: "•" };

  // ---------- simulated sites (illustration only) ----------
  const SIM = [
    ["Aklavik", "NT", "Peel Channel, Mackenzie Delta", 68.22, -135.01, "05-30"],
    ["Fort Good Hope", "NT", "Mackenzie River", 66.26, -128.63, "05-20"],
    ["Fort McMurray", "AB", "Athabasca and Clearwater rivers", 56.73, -111.38, "04-25"],
    ["Peace River", "AB", "Peace River", 56.24, -117.29, "04-15"],
    ["Fort Vermilion", "AB", "Peace River", 58.39, -116.0, "05-01"],
    ["Attawapiskat", "ON", "Attawapiskat River", 52.93, -82.43, "05-05"],
    ["Dawson City", "YT", "Yukon and Klondike rivers", 64.06, -139.43, "05-08"],
    ["Perth-Andover", "NB", "Saint John River", 46.74, -67.7, "04-10"],
    ["Badger", "NL", "Exploits River", 49.0, -56.04, "03-25"],
    ["Saint-Raymond", "QC", "Sainte-Anne River", 46.9, -71.83, "03-20"],
  ].map(([name, prov, river, lat, lon, typical]) => ({ name, prov, river, lat, lon, typical, sim: true }));
  const HAY = { name: "Hay River", prov: "NT", river: "Hay River", lat: 60.82, lon: -115.79, sim: false };

  // ---------- blind-test sites (real RCM data, one locked prediction per spring) ----------
  const BL = (window.HRFW.blind || { sites: {} }).sites;
  const BLIND = [["fort_simpson", "Fort Simpson", "NT", "Mackenzie and Liard rivers"],
                 ["albany", "Fort Albany and Kashechewan", "ON", "Albany River estuary"]]
    .filter(([id]) => BL[id])
    .map(([id, name, prov, river]) => ({ id, name, prov, river, lat: BL[id].lat, lon: BL[id].lon, sim: false, blind: true }));
  const LEVEL_STATUS = { Low: "Safe", Watch: "Possible", Warning: "Possible", Critical: "High danger" };
  const BLIND_SEASON = ["04-01", "06-15"];
  function blindRow(site, iso) {
    return BL[site.id].years.find((r) => r.year === Number(iso.slice(0, 4))) || null;
  }
  function blindStatus(site, iso) {
    const r = blindRow(site, iso);
    if (!r) return "None";
    const md = iso.slice(5);
    if (md < BLIND_SEASON[0] || md > BLIND_SEASON[1]) return "Safe";
    return LEVEL_STATUS[r.level] || "None";
  }

  // ---------- date helpers ----------
  const pad = (n) => String(n).padStart(2, "0");
  const toIso = (d) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  const parse = (s) => new Date(s + "T00:00:00Z");
  const addDays = (s, n) => { const d = parse(s); d.setUTCDate(d.getUTCDate() + n); return toIso(d); };
  const daysBetween = (a, b) => Math.round((parse(b) - parse(a)) / 86400000);
  const fmt = (s, year) => parse(s).toLocaleDateString("en-CA", Object.assign({ timeZone: "UTC", month: "short", day: "numeric" }, year ? { year: "numeric" } : {}));
  const FIRST = `${W.first_year}-01-01`, LAST = W.last_day;
  const clamp = (s) => (s < FIRST ? FIRST : s > LAST ? LAST : s);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function hash01(text) {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
    return ((h >>> 0) % 10000) / 10000;
  }

  // ---------- Hay River (real) ----------
  function hayRecord(iso) {
    const Y = W.years[iso.slice(0, 4)];
    return Y ? Y.days.find((r) => r.d === iso.slice(5)) || null : null;
  }
  function hayStatus(iso) {
    const r = hayRecord(iso);
    if (!r) return "Safe";                       // July to December: no breakup risk
    if (r.over) return "Safe";
    return r.status || "None";                    // None = winter, outlook not started
  }

  // ---------- simulated status ----------
  function simStatus(site, iso) {
    const year = iso.slice(0, 4);
    const typical = `${year}-${site.typical}`;
    const until = daysBetween(iso, typical);
    const severity = hash01(site.name + year);
    if (until > 28 || until < -7) return "Safe";
    if (severity > 0.72 && until <= 14) return "High danger";
    return "Possible";
  }

  // ---------- maps ----------
  const BASE = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
  function baseLayers(map) {
    L.tileLayer(BASE + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: "Tiles &copy; Esri" }).addTo(map);
    map.createPane("labels").style.zIndex = 450;
    map.getPane("labels").style.pointerEvents = "none";
    L.tileLayer(BASE + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, pane: "labels" }).addTo(map);
  }
  // SINGLE = map explorer (index.html): one map. Zoomed out it shows the Canada summary
  // (site markers), zoomed in it shows Hay River places, buildings, ice and flooding.
  const SINGLE = !document.getElementById("canada");
  const CANADA_BOUNDS = [[42, -141], [70, -53]];
  const DETAIL_ZOOM = 10;
  let canada = null;
  if (!SINGLE) {
    canada = L.map("canada", { minZoom: 3, maxBounds: [[35, -160], [80, -40]] });
    baseLayers(canada);
    canada.fitBounds(CANADA_BOUNDS);
  }

  // Wheel zoom: one scroll notch zooms about one full level (twice as close); a smaller
  // wheelPxPerZoomLevel means a bigger zoom per notch. Quarter-level snapping keeps it smooth.
  const SMOOTH = { zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 45, wheelDebounceTime: 20 };
  const zoom = L.map("zoom", SINGLE
    ? Object.assign({ minZoom: 3, maxZoom: 18, zoomControl: false, maxBounds: [[35, -160], [80, -40]] }, SMOOTH)
    : Object.assign({ minZoom: 11, maxZoom: 18 }, SMOOTH));
  if (SINGLE) {
    zoom.createPane("summary").style.zIndex = 640;
    const mode = () => {
      const detail = zoom.getZoom() >= DETAIL_ZOOM;
      zoom.getContainer().classList.toggle("z-detail", detail);
      zoom.getContainer().classList.toggle("z-summary", !detail);
      document.body.classList.toggle("map-summary", !detail);
    };
    zoom.on("zoomend", mode);
    zoom.whenReady(mode);
  }
  // Base maps for the zoomed view: street names by default, light grey, or a satellite photo.
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  // Tiles: keep extra tiles around the view (smoother panning) and fetch new ones after a zoom ends.
  const TILE = { keepBuffer: 4, updateWhenZooming: false };
  const zoomBases = {
    "Streets (road names)": L.tileLayer(ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}",
      Object.assign({ maxZoom: 18, attribution: "Tiles &copy; Esri" }, TILE)),
    "Light grey": L.tileLayer(ESRI + "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      Object.assign({ maxZoom: 16, maxNativeZoom: 16, attribution: "Tiles &copy; Esri" }, TILE)),
    "Satellite photo": L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}",
      Object.assign({ maxZoom: 18, attribution: "Imagery &copy; Esri" }, TILE)),
  };
  zoomBases["Streets (road names)"].addTo(zoom);
  const view = W.view;                             // west, south, east, north
  zoom.fitBounds([[view[1], view[0]], [view[3], view[2]]]);
  zoom.createPane("flood").style.zIndex = 405;
  zoom.createPane("buildings").style.zIndex = 412;
  zoom.createPane("ice").style.zIndex = 420;
  zoom.createPane("places").style.zIndex = 430;
  L.polyline(W.jam_zone, { pane: "places", color: "#26374a", weight: 2.5, dashArray: "6 6", opacity: 0.9, interactive: false }).addTo(zoom);
  const iceGroup = L.layerGroup().addTo(zoom);
  const floodGroup = L.layerGroup().addTo(zoom);
  const facilityGroup = L.layerGroup().addTo(zoom);
  const buildingGroup = L.layerGroup().addTo(zoom);
  // The buildings sit in an inner group so the explorer can take them off the map when
  // zoomed out to Canada (nothing to see there, and redrawing 1,700 outlines is the slow part)
  // without unticking "Buildings by flood risk" in the layer switcher.
  const buildingInner = L.layerGroup().addTo(buildingGroup);
  // Labels on facilities only when zoomed in enough to read them.
  const labelZoom = () => zoom.getContainer().classList.toggle("z-labels", zoom.getZoom() >= 14);
  zoom.on("zoomend", labelZoom);

  // Buildings (houses etc.) from OpenStreetMap, coloured each day by flood risk.
  const BTYPE = { house: "House", detached: "House", residential: "Residential", apartments: "Apartments",
                  commercial: "Commercial", retail: "Store", industrial: "Industrial", hospital: "Hospital",
                  school: "School", church: "Church", garage: "Garage", shed: "Shed", yes: "Building" };
  const bRenderer = L.canvas({ pane: "buildings" });
  let currentR = null;
  const buildings = (window.HRFW.buildings || []).map((b) => {
    const poly = L.polygon(b.c.map(([x, y]) => [y, x]), { renderer: bRenderer, weight: 0.8, color: "#8a96a3",
                                                          fillColor: "#d5dae0", fillOpacity: 0.8 });
    poly.bindTooltip(() => {
      const lvl = currentR && currentR.lake_high ? b.lh : b.lt;
      const head = `${b.n ? esc(b.n) + " &middot; " : ""}${BTYPE[b.t] || "Building"}`;
      if (lvl == null) return `${head}<br>Not flooded up to 172 m`;
      const ch = currentR && currentR.status && !currentR.over ? chanceAbove(currentR, lvl) : null;
      return `${head}<br>Floods if the river reaches ${lvl.toFixed(1)} m${ch == null ? "" : `<br>${pct(ch)} chance this spring`}`;
    }, { sticky: true });
    poly.addTo(buildingInner);
    return { poly, b, fill: null };
  });
  if (SINGLE) {
    const showBuildings = () => {
      const detail = zoom.getZoom() >= DETAIL_ZOOM;
      if (detail && !buildingGroup.hasLayer(buildingInner)) buildingGroup.addLayer(buildingInner);
      if (!detail && buildingGroup.hasLayer(buildingInner)) buildingGroup.removeLayer(buildingInner);
    };
    zoom.on("zoomend", showBuildings);
    showBuildings();
  }

  // Swap a picture layer (RCM ice, flood area) without a blank gap: keep it if the picture
  // is unchanged, otherwise remove the old one only once the new one has loaded.
  function setOverlay(group, url, bounds, opts) {
    const old = group.getLayers();
    if (url && old.length === 1 && old[0]._url === url) return;
    if (!url) { group.clearLayers(); return; }
    const lyr = L.imageOverlay(url, bounds, opts);
    lyr.once("load error", () => old.forEach((l) => group.removeLayer(l)));
    group.addLayer(lyr);
  }

  function styleBuildings(r) {
    currentR = r;
    const active = r && r.status && !r.over;
    buildings.forEach((item) => {
      const { poly, b } = item;
      const lvl = r && r.lake_high ? b.lh : b.lt;
      const ch = active && lvl != null ? chanceAbove(r, lvl) : 0;
      // Same risk colours as places; buildings not at risk stay a quiet grey.
      const fill = ch >= 50 ? COLOR["High danger"] : ch >= 10 ? COLOR.Possible : "#d5dae0";
      if (fill === item.fill) return;              // unchanged: skip the redraw
      item.fill = fill;
      poly.setStyle({ fillColor: fill, color: ch >= 10 ? "#26374a" : "#8a96a3", fillOpacity: ch >= 10 ? 0.9 : 0.8 });
    });
  }

  const state = { date: "2022-04-25", site: HAY };
  const markers = [];
  // Site outline: Hay River thin solid, blind-test sites thick solid, simulated thin dashed.
  const baseWeight = (site) => (site.blind ? 4 : 2);
  [HAY].concat(BLIND, SIM).forEach((site) => {
    const m = L.circleMarker([site.lat, site.lon], {
      radius: site.sim ? 8 : site.blind ? 10 : 11, weight: baseWeight(site), color: site.sim ? "#5d6b79" : "#26374a",
      dashArray: site.sim ? "3 3" : null, fillOpacity: site.sim ? 0.75 : 1,
      pane: SINGLE ? "summary" : "overlayPane",
    }).addTo(SINGLE ? zoom : canada);
    m.on("click", () => {
      state.site = site;
      render();
      if (SINGLE && site === HAY) zoom.flyToBounds([[view[1], view[0]], [view[3], view[2]]], { duration: 1 });
    });
    markers.push({ site, m });
  });

  // ---------- rendering ----------
  function statusOf(site) {
    if (site.sim) return simStatus(site, state.date);
    if (site.blind) return blindStatus(site, state.date);
    return hayStatus(state.date);
  }

  function renderMarkers() {
    markers.forEach(({ site, m }) => {
      const st = statusOf(site);
      const selected = site === state.site;
      m.setStyle({ fillColor: COLOR[st], weight: baseWeight(site) + (selected ? 2 : 0),
                   color: selected ? "#26374a" : (site.sim ? "#5d6b79" : "#26374a") });
      m.setRadius((site.sim ? 8 : site.blind ? 10 : 11) + (selected ? 3 : 0));
      m.bindTooltip(`<strong>${esc(site.name)}, ${site.prov}</strong><br>${st === "None" ? "No prediction" : st}` +
        `${site.sim ? "<br><em>Simulated example</em>" : site.blind ? "<br><em>Blind test: one prediction per spring</em>" : ""}`);
    });
  }

  function whenText(iso, r) {
    const md = iso.slice(5);
    const year = iso.slice(0, 4);
    if (!r) {
      const fu = (W.years[year] || {}).freeze_up;
      if (md >= "11-01" && fu && iso >= fu) return { main: `River ice is forming (freeze-up on ${fmt(fu)}).`, sub: "Next breakup danger window: usually late April to mid May." };
      return { main: "Open water season. No ice-jam flood risk until spring.", sub: "Next breakup danger window: usually late April to mid May." };
    }
    if (r.over) return { main: "Breakup is over for this year.", sub: "The ice has cleared or the river has dropped. Next danger window: next spring." };
    if (!r.win) return { main: "Danger window not available for this day.", sub: "" };
    const [a, b, c] = r.win.map((d) => `${year}-${d}`);
    const da = daysBetween(iso, a), dc = daysBetween(iso, c);
    if (dc <= 0 || da <= 0) {
      return { main: `<strong>Breakup could start any day now</strong>, most likely by ${fmt(c)}.`, sub: "This is when ice jams form and floods happen." };
    }
    return { main: `Breakup danger window: <strong>${fmt(a)} to ${fmt(c)}</strong> (in ${da} to ${dc} days).`,
             sub: `Most likely around ${fmt(b)}. This is when ice jams form and floods happen.` };
  }

  function historyStrip(iso) {
    const year = iso.slice(0, 4);
    const Y = W.years[year];
    const start = `${year}-03-01`;
    if (!Y || iso < start) return "";
    const end = iso.slice(5) > "06-30" ? `${year}-06-30` : iso;   // spring only
    let cells = "", firstPossible = null, firstDanger = null;
    for (let d = start; d <= end; d = addDays(d, 1)) {
      const st = hayStatus(d);
      cells += `<span style="background:${COLOR[st]}" title="${fmt(d)}: ${st}"></span>`;
      if (!firstPossible && (st === "Possible" || st === "High danger")) firstPossible = d;
      if (!firstDanger && st === "High danger") firstDanger = d;
    }
    const lead = [];
    if (firstPossible) lead.push(`First warning: <strong>${fmt(firstPossible)}</strong>`);
    if (firstDanger) lead.push(`first High danger: <strong>${fmt(firstDanger)}</strong>`);
    return `<div class="history"><div class="strip">${cells}</div>
      <div class="axis"><span>Mar 1</span><span>${fmt(end)}</span></div>
      <p>${lead.length ? lead.join(", ") + "." : "No warnings so far this spring."}</p></div>`;
  }

  function outcome(iso) {
    const year = iso.slice(0, 4);
    const Y = W.years[year];
    if (!Y) return "";
    let txt;
    if (Y.peak_level && Y.peak_date) {
      txt = `Spring peak ${Y.peak_level.toFixed(1)} m on ${fmt(Y.peak_date)}. ${Y.flood ? "The town flooded." : "No documented flooding."}`;
    } else {
      const obs = Y.days.filter((r) => r.obs != null && r.d >= "03-01");
      if (!obs.length) return "";
      const top = obs.reduce((m, r) => (r.obs > m.obs ? r : m));
      txt = `Highest daily river level this spring: ${top.obs.toFixed(1)} m on ${fmt(`${year}-${top.d}`)}` +
        `${Number(year) >= 2025 ? " (provisional data)" : ""}. ${Y.flood ? "The town flooded." : "No documented flooding."}`;
    }
    return `<details class="check"><summary>Check: what actually happened in ${year}</summary><p>${txt} The model never saw this year.</p></details>`;
  }

  function renderDetail() {
    const el = document.getElementById("detail");
    const site = state.site;
    const st = statusOf(site);
    if (site.blind) {
      const r = blindRow(site, state.date);
      const yr = state.date.slice(0, 4);
      const head = `<div class="site-head"><h2>${esc(site.name)}, ${site.prov}</h2><span class="chip">Blind test</span></div>
        <p class="site-sub">${esc(site.river)} &middot; RCM images and air temperature only</p>`;
      if (!r) {
        el.innerHTML = head + `<span class="status None">${ICON.None} No prediction</span>
          <p class="sub">The blind test covers springs 2021 to 2026 only.</p>`;
        return;
      }
      const md = state.date.slice(5);
      const inSeason = md >= BLIND_SEASON[0] && md <= BLIND_SEASON[1];
      el.innerHTML = head + `<span class="status ${st.split(" ")[0]}">${ICON[st]} ${st}</span>
        <span class="chip">${esc(r.level)}</span><span class="chip">Confidence: ${esc(r.confidence)}</span>
        ${inSeason ? "" : `<p class="sub">Outside the breakup season. Spring ${yr} prediction shown below.</p>`}
        <p class="big-when">Spring ${yr}: <strong>${esc(r.level)}</strong>${r.likelihood != null ? `, ${r.likelihood}% of melt-season images above the jam threshold` : ""}.</p>
        <p class="sub">${esc(r.why)}</p>
        ${!r.main ? '<p class="sub">100 m images only: reported separately, low confidence.</p>' : ""}
        <p class="sim-note">One locked prediction per spring from the blind test, made with the Hay River rules and
          no retraining. Not a daily forecast. Outcome: not checked yet.</p>`;
      return;
    }
    if (site.sim) {
      const typical = fmt(`${state.date.slice(0, 4)}-${site.typical}`);
      el.innerHTML = `<div class="site-head"><h2>${esc(site.name)}, ${site.prov}</h2><span class="chip">Simulated</span></div>
        <p class="site-sub">${esc(site.river)}</p>
        <span class="status ${st.split(" ")[0]}">${ICON[st]} ${st}</span>
        <p class="big-when">Typical breakup: around ${typical}.</p>
        <p class="sim-note">Simulated example. This site is not monitored yet, so the colour is made up to show how a
          warning would look once the model is trained here with local RCM images and river gauges.</p>`;
      return;
    }
    const r = hayRecord(state.date);
    const when = whenText(state.date, r);
    let statusHtml, chance = "";
    if (r && r.over) {
      statusHtml = `<span class="status Safe">${ICON.Safe} Safe</span>`;
    } else if (r && r.status) {
      statusHtml = `<span class="status ${r.status.split(" ")[0]}">${ICON[r.status]} ${r.status}</span>
        <span class="chip">${r.level}</span>${r.early ? '<span class="chip">Early outlook</span>' : ""}`;
      chance = `<p class="sub"><strong>${pct(r.chance)}</strong> chance the spring peak reaches flood level (${W.flood_level_m} m).</p>`;
    } else if (r) {
      statusHtml = `<span class="status None">${ICON.None} No outlook yet</span>`;
      chance = `<p class="sub">Winter: the upstream river gauge restarts in March, when the outlook begins.</p>`;
    } else {
      statusHtml = `<span class="status Safe">${ICON.Safe} Safe</span>`;
    }
    el.innerHTML = `<div class="site-head"><h2>Hay River, NT</h2><span class="chip">Real data</span></div>
      <p class="site-sub">${fmt(state.date, true)} &middot; Hay River, from Great Slave Lake up past the town</p>
      ${statusHtml}${chance}
      <p class="big-when">${when.main}</p><p class="sub">${when.sub}</p>
      ${historyStrip(state.date)}
      ${outcome(state.date)}`;
  }

  // ---------- helpers for the decision and the places ----------
  const P = (window.HRFW.places || { places: [] });
  const placeLayer = L.layerGroup().addTo(zoom);
  L.control.layers(zoomBases, {
    "Buildings by flood risk": buildingGroup,
    "Hospitals, schools and services": facilityGroup,
    "Neighbourhoods and routes": placeLayer,
    "RCM river ice": iceGroup,
    "Estimated flooded land": floodGroup,
  }, { collapsed: true, position: "topright" }).addTo(zoom);
  if (SINGLE) L.control.scale({ imperial: false, position: "bottomright" }).addTo(zoom);
  function facilityLetter(p) {
    if (p.cat === "Hospital") return "H";
    if (p.cat === "Health centre") return "+";
    if (p.cat === "School") return "S";
    if (p.cat === "Emergency services") return /rcmp|police/i.test(p.name) ? "P" : "F";
    if (p.cat === "Community centre") return "C";
    if (p.cat === "Airport") return "A";
    if (p.cat === "Fuel") return "G";
    if (p.cat === "Town hall") return "T";
    return "•";
  }
  const ROUTE_WORDS = { "High danger": "Likely cut", Possible: "May be cut", Safe: "Open", None: "No outlook yet" };

  function factorText(name, value) {
    if (name.startsWith("Great Slave")) return `${Math.abs(value).toFixed(2)} m ${value >= 0 ? "above" : "below"} its long-term average`;
    if (name.startsWith("Ice")) return `about ${Math.round(value)} cm thick (estimated)`;
    if (name.startsWith("Rise")) return `${value >= 0 ? "up" : "down"} ${Math.abs(Math.round(value))} m³/s over the last 7 days`;
    return `${Math.round(value)} m³/s`;
  }
  function rcmImage(r) {
    if (!r || !r.rcm || !W.ice[r.rcm.id]) return null;
    const img = W.ice[r.rcm.id];
    return Object.assign({ age: daysBetween(img.time.slice(0, 10), state.date) }, img);
  }
  function dayConfidence(r) {
    if (!r || r.over || !r.status) return null;
    if (r.d < "04-01") return { level: "Low", why: "early outlook (before April 1): the ice has not started to move" };
    const img = rcmImage(r);
    if (img && img.age <= 3) return { level: "High", why: `river data are current and an RCM image is ${img.age === 0 ? "from today" : img.age + " days old"}` };
    return { level: "Medium", why: "river data are current, but there is no RCM image from the last 3 days" };
  }
  function chanceAbove(r, level) {
    if (level == null) return 0;
    const q = W.resid_q;
    return Math.round((100 * q.filter((e) => r.median + e >= level).length) / q.length);
  }
  function placeStatus(ch) { return ch >= 50 ? "High danger" : ch >= 10 ? "Possible" : "Safe"; }
  // The model can never be that sure: show the ends of the scale as "over 95%" / "under 5%".
  const pct = (ch) => (ch >= 96 ? "over 95%" : ch <= 4 ? "under 5%" : `${ch}%`);

  function assessPlaces(r) {
    const mouthKey = r && r.lake_high ? "high" : "typical";
    const active = r && !r.over && r.status;
    return P.places.map((p) => {
      const lvl = p.level[mouthKey];
      const ch = active ? chanceAbove(r, lvl) : 0;
      const st = active ? placeStatus(ch) : (r && !r.over && !r.status ? "None" : "Safe");
      return Object.assign({}, p, { lvl, chance: ch, st });
    }).sort((a, b) => (b.chance - a.chance) || ((a.lvl || 999) - (b.lvl || 999)));
  }

  // ---------- decision bullets + full analysis ----------
  function renderDecision(r, places) {
    const pts = [];
    const img = rcmImage(r);
    const conf = dayConfidence(r);
    if (!r) {
      pts.push("Open water or freeze-up season: there is no river ice that can jam, so there is no breakup flood risk until spring.");
    } else if (r.over) {
      pts.push(`Breakup is over for ${state.date.slice(0, 4)}: thaw has passed ${r.tdd.toFixed(0)} degree-days, the RCM image shows the river clearing, or the river has dropped well below its spring high.`);
    } else if (!r.status) {
      pts.push("Winter: the upstream river gauge restarts in March, so the full forecast is not available yet.");
      if (r.win) pts.push(`Based on temperatures alone, the breakup danger window is expected ${fmt(`${state.date.slice(0, 4)}-${r.win[0]}`)} to ${fmt(`${state.date.slice(0, 4)}-${r.win[2]}`)}.`);
    } else {
      pts.push(`Forecast spring peak at the town gauge: <strong>${r.median.toFixed(1)} m</strong> (likely ${r.p10.toFixed(1)} to ${r.p90.toFixed(1)} m), so the risk is <strong>${r.level}</strong>.`);
      const top = r.all.slice().sort((a, b) => Math.abs(b[2]) - Math.abs(a[2])).slice(0, 2);
      pts.push("Biggest factors: " + top.map(([n, v, c]) => `${esc(n)} (${factorText(n, v)}, ${c >= 0 ? "+" : ""}${c.toFixed(1)} m)`).join("; ") + ".");
      if (img) {
        const effect = r.level !== r.model_level ? `, so RCM ${["Low", "Watch", "Warning", "Critical"].indexOf(r.level) > ["Low", "Watch", "Warning", "Critical"].indexOf(r.model_level) ? "raised" : "lowered"} the risk one level` : "";
        pts.push(`RCM image (${fmt(img.time.slice(0, 10))}): ${r.rcm.rubble}% rubble or rough ice and ${r.rcm.water}% open water from the lake to town${r.rcm.melt ? "" : " (winter ice cover, before melt)"}${effect}.`);
      } else {
        pts.push("No RCM image of the river in the last 10 days: the forecast uses river and weather data only.");
      }
      if (r.win) pts.push(`Breakup danger window: ${fmt(`${state.date.slice(0, 4)}-${r.win[0]}`)} to ${fmt(`${state.date.slice(0, 4)}-${r.win[2]}`)}, from the thaw so far (${r.tdd.toFixed(0)} of the usual ${W.tdd_at_peak[0]} to ${W.tdd_at_peak[2]} degree-days).`);
      const hi = places.filter((p) => p.st === "High danger").length, po = places.filter((p) => p.st === "Possible").length;
      pts.push(`${hi} place${hi === 1 ? "" : "s"} at high danger and ${po} possibly affected (list below). Confidence: <strong>${conf.level}</strong>, because ${conf.why}.`);
    }
    document.getElementById("why").innerHTML = pts.map((p) => `<li>${p}</li>`).join("");
    document.getElementById("analysis").innerHTML = fullAnalysis(r, places, img, conf);
  }

  function fullAnalysis(r, places, img, conf) {
    const year = state.date.slice(0, 4);
    const lv = ["Low", "Watch", "Warning", "Critical"];
    let h = `<h3>1. What the "AI" is</h3>
      <p>Two parts, both explainable. (a) A statistical model (ridge regression) that learned from 46 springs (1976 to 2024) how the
      spring peak water level at the town gauge relates to four measurements. Each spring shown here was forecast by a version that never saw
      it. (b) Fixed rules for RCM satellite radar images that check whether rubble ice is building up near the river mouth. It is not a
      chatbot and does not guess: every number below can be traced.</p>`;
    if (r && r.status && !r.over) {
      h += `<h3>2. Today's inputs and how much each one moved the forecast</h3>
        <table><tr><th>Factor</th><th>Today</th><th class="num">Effect on forecast</th></tr>
        <tr><td>Starting point (average spring)</td><td></td><td class="num">${r.base.toFixed(2)} m</td></tr>
        ${r.all.map(([n, v, c]) => `<tr><td>${esc(n)}</td><td>${factorText(n, v)}</td><td class="num">${c >= 0 ? "+" : ""}${c.toFixed(2)} m</td></tr>`).join("")}
        <tr><th>Forecast spring peak</th><td></td><th class="num">${r.median.toFixed(2)} m</th></tr></table>
        <p>Likely range ${r.p10.toFixed(1)} to ${r.p90.toFixed(1)} m (10% to 90%), from how far past forecasts were off.
        Chance the peak reaches ${W.watch_m} m (the lowest level with documented flooding in town): <strong>${pct(r.chance)}</strong>.</p>
        <h3>3. How the risk level was set</h3>
        <ul><li>Critical: most likely peak at or above ${W.warning_m} m (1985 and 1992 flood levels).</li>
        <li>Warning: most likely peak at or above ${W.watch_m} m, or the high end at or above ${W.warning_m} m.</li>
        <li>Watch: the high end at or above ${W.watch_m} m.</li><li>Low: otherwise.</li></ul>
        <p>Today: most likely ${r.median.toFixed(1)} m, high end ${r.p90.toFixed(1)} m, so the model alone gives <strong>${r.model_level}</strong>.
        ${r.level !== r.model_level ? `After the RCM check the final level is <strong>${r.level}</strong>.` : "The RCM check did not change it."}</p>`;
      h += `<h3>4. RCM satellite evidence</h3>`;
      if (img) {
        h += `<p>Image: ${fmt(img.time.slice(0, 10), true)} ${img.time.slice(11)} UTC (${img.age === 0 ? "today" : img.age + " days old"}).
          In the jam zone (Great Slave Lake to just past town): ${r.rcm.rubble}% rubble or rough ice, ${r.rcm.water}% open water.</p>
          <ul><li>Melt has ${r.tdd >= W.melt_tdd ? "started" : "not started"} (${r.tdd.toFixed(0)} thawing degree-days; the rule needs ${W.melt_tdd}).</li>
          <li>Rule: during melt, rubble at or above ${W.rcm_threshold}% of the jam zone raises the risk one level; 50% or more open water lowers it one level.</li>
          <li>The ${W.rcm_threshold}% threshold sits halfway between the 2022 flood year (91 to 95%) and the 2023 normal year (31 to 76%).</li></ul>`;
      } else {
        h += `<p>No RCM image of the river in the last 10 days, so the forecast uses river and weather data only.</p>`;
      }
      if (r.win) {
        h += `<h3>5. When: the breakup danger window</h3>
          <p>Breakup at Hay River usually comes once ${W.tdd_at_peak[0]} to ${W.tdd_at_peak[2]} thawing degree-days have built up since March 1
          (2002 to 2024). Thaw so far: ${r.tdd.toFixed(0)}. Every other spring's weather since 1944 is replayed forward from today; the middle
          half of the dates gives the window <strong>${fmt(`${year}-${r.win[0]}`)} to ${fmt(`${year}-${r.win[2]}`)}</strong>, most likely ${fmt(`${year}-${r.win[1]}`)}.
          Check on past springs: the real peak fell inside a window issued on April 1 in ${W.window_check["04-01"].inside} of
          ${W.window_check["04-01"].years} springs, and on April 15 in ${W.window_check["04-15"].inside} of ${W.window_check["04-15"].years}.</p>`;
      }
      h += `<h3>${r.win ? 6 : 5}. How places were assessed</h3>
        <p>For each place, the flood map method (2020 lidar ground model and a sloping ice-jam water surface) finds the lowest river level
        at the town gauge at which it starts to flood. Today uses the ${r.lake_high ? "high" : "typical"} Great Slave Lake case.
        The chance for a place is the chance the spring peak reaches that level. High danger: 50% or more; Possible: 10% or more.
        No place is given a level below ${P.documented_floor_m} m, because no flooding in town has been documented below that.
        Place confidence is at most Medium, because the flood map is a simplified estimate.</p>`;
    } else {
      h += `<p>${!r ? "Open water or freeze-up season: no forecast is made." : r.over ? "Breakup is over: no forecast is made until next spring." :
        "Winter: the forecast starts on March 1, when the upstream river gauge restarts."}</p>`;
    }
    const s7 = W.skill.find((x) => x.days_before_peak === 7);
    const n = r && r.status && !r.over ? (r.win ? 7 : 6) : 2;      // keep section numbers in order
    h += `<h3>${n}. How well it has worked</h3>
      <ul><li>Seven days before the peak, the forecast was off by ${s7.MAE_model.toFixed(2)} m on average, against ${s7.MAE_upstream.toFixed(2)} m using
      upstream flow alone and ${s7.MAE_climatology.toFixed(2)} m guessing the long-term average (46 springs, each tested without itself).</li>
      <li>All ${s7.flood_years_tested} documented flood springs that could be tested were rated Warning or higher a week ahead. About 1 in 3 normal
      springs was also rated Warning: the system leans cautious.</li>
      <li>Blind test on two other rivers (Fort Simpson and Albany River): predictions are locked, outcomes not checked yet.</li></ul>
      <h3>${n + 1}. Data and limitations</h3>
      <ul><li>River gauges: Water Survey of Canada${Number(year) >= 2025 ? " (provisional data for 2025 and 2026)" : ""}. Weather: Hay River airport.
      RCM: RADARSAT Constellation Mission, 16 m images.</li>
      <li>The gauge level does not decide flooding by itself: where the ice jams matters. 1989, 1994 and 2021 peaked above 168 m without documented flooding.</li>
      <li>RCM cannot tell smooth ice from calm water, and an image is only a snapshot.</li>
      <li>Flood areas are estimates from elevation, not observed.</li>
      <li>Not an official forecast: always follow the Town of Hay River and GNWT.</li></ul>`;
    return h;
  }

  // ---------- places ----------
  function renderPlaces(r, places) {
    const conf = dayConfidence(r);
    const pConf = conf ? (conf.level === "Low" ? "Low" : "Medium") : null;
    document.getElementById("placesIntro").innerHTML = r && r.status && !r.over
      ? `If the river peaks around <strong>${r.median.toFixed(1)} m</strong> (likely ${r.p10.toFixed(1)} to ${r.p90.toFixed(1)} m).
         Place confidence: <strong>${pConf}</strong>. Click a place to find it on the map.`
      : "No active forecast today. The levels show when each place would start to flood, for planning ahead.";
    const groups = [["Neighbourhood", "Neighbourhoods"],
                    ["Evacuation route", "Evacuation routes and bridges"],
                    [null, "Critical facilities"]];
    let html = "";
    groups.forEach(([cat, title]) => {
      const list = places.filter((p) => (cat ? p.cat === cat : !["Neighbourhood", "Evacuation route"].includes(p.cat)));
      if (!list.length) return;
      html += `<h3>${title}</h3>`;
      list.forEach((p, i) => {
        const word = p.cat === "Evacuation route" ? ROUTE_WORDS[p.st] : (p.st === "None" ? "No outlook yet" : p.st);
        const lvlTxt = p.lvl == null ? "not reached up to 172 m (above the 2022 record of 170.9 m)" : `starts to flood if the river reaches ${p.lvl.toFixed(1)} m`;
        const extra = p.cat === "Neighbourhood" && p.buildings ? ` (${p.buildings} buildings; 1 in 10 flood at this level)` : "";
        const chance = r && r.status && !r.over ? ` &middot; ${pct(p.chance)} chance &middot; confidence ${pConf}` : "";
        html += `<div class="place" tabindex="0" data-name="${esc(p.name)}">
          <span class="pname">${esc(p.name)}</span><span class="pill ${p.st.split(" ")[0]}">${esc(word)}</span>
          <span class="pmeta">${esc(p.cat)} &middot; ${lvlTxt}${extra}${chance}</span></div>`;
      });
    });
    document.getElementById("places").innerHTML = html;

    placeLayer.clearLayers();
    facilityGroup.clearLayers();
    const markers = {};
    places.forEach((p) => {
      const popup = `<strong>${esc(p.name)}</strong><br>${esc(p.cat)}<br>` +
        (p.cat === "Evacuation route" ? ROUTE_WORDS[p.st] : p.st) +
        (r && r.status && !r.over ? ` (${pct(p.chance)} chance)` : "") +
        `<br>${p.lvl == null ? "Not reached up to 172 m" : "Floods from " + p.lvl.toFixed(1) + " m at the town gauge"}` +
        (p.note ? `<br><em>${esc(p.note)}</em>` : "");
      let m;
      if (p.cat === "Neighbourhood" || p.cat === "Evacuation route") {
        m = L.circleMarker([p.lat, p.lon], {
          pane: "places", radius: p.cat === "Neighbourhood" ? 9 : 7, weight: 2, color: "#26374a",
          fillColor: COLOR[p.st] || COLOR.None, fillOpacity: 0.95,
        }).bindPopup(popup).addTo(placeLayer);
      } else {
        // Facilities: a letter icon (H hospital, S school, ...) outlined in the danger colour, with its name.
        const letter = facilityLetter(p);
        m = L.marker([p.lat, p.lon], {
          pane: "places", icon: L.divIcon({ className: "", iconSize: [26, 26], iconAnchor: [13, 13],
            html: `<span class="ficon" style="border-color:${COLOR[p.st] || COLOR.None}">${letter}</span>` }),
          title: p.name,
        }).bindPopup(popup).bindTooltip(esc(p.name), { permanent: true, direction: "right", offset: [12, 0], className: "flabel" })
          .addTo(facilityGroup);
      }
      markers[p.name] = m;
    });
    document.querySelectorAll("#places .place").forEach((el) => {
      const go = () => { const m = markers[el.dataset.name]; if (m) { zoom.setView(m.getLatLng(), 14); m.openPopup(); } };
      el.addEventListener("click", go);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });
  }

  function renderWhy() {
    const card = document.getElementById("whyCard");
    const dCard = document.getElementById("decisionCard");
    const hide = state.site.sim || state.site.blind;
    card.hidden = hide;
    dCard.hidden = hide;
    if (hide && !SINGLE) return;   // the explorer's map always shows Hay River for the chosen day
    const r = hayRecord(state.date);
    const cap = [];
    const img = rcmImage(r);
    setOverlay(iceGroup, img && img.img, img && img.bounds, { pane: "ice", interactive: false });
    let floodUrl = null, floodBounds = null;
    if (img) {
      cap.push(`RCM image ${fmt(img.time.slice(0, 10), true)} ${img.time.slice(11)} UTC (${img.age === 0 ? "today" : img.age + " day" + (img.age > 1 ? "s" : "") + " old"})`);
    } else if (r && !r.over) {
      cap.push("No RCM image in the last 10 days");
    }
    if (r && r.median && r.median >= W.flood_levels[0] && !r.over) {
      const lvl = Math.min(Math.max(Math.round(r.median * 2) / 2, W.flood_levels[0]), W.flood_levels[W.flood_levels.length - 1]);
      const mouth = r.lake_high ? W.mouths[1] : W.mouths[0];
      const f = W.flood[`${lvl.toFixed(2)}|${mouth.toFixed(2)}`];
      if (f) {
        // Light enough that road names underneath stay readable.
        floodUrl = f.img;
        floodBounds = f.bounds;
        cap.push(`teal area: estimated flooding if the river peaks at ${r.median.toFixed(1)} m`);
      }
    }
    setOverlay(floodGroup, floodUrl, floodBounds, { pane: "flood", interactive: false, opacity: 0.45 });
    document.getElementById("zoomCap").textContent = cap.join(" · ") || "Hay River";
    styleBuildings(r);
    labelZoom();
    const places = assessPlaces(r);
    renderDecision(r, places);
    renderPlaces(r, places);
  }

  const moreBtn = document.getElementById("moreBtn");
  moreBtn.addEventListener("click", () => {
    const box = document.getElementById("analysis");
    box.hidden = !box.hidden;
    moreBtn.setAttribute("aria-expanded", String(!box.hidden));
    moreBtn.textContent = box.hidden ? "Show full analysis" : "Hide full analysis";
  });

  function render() {
    document.getElementById("day").value = state.date;
    renderMarkers();
    renderDetail();
    renderWhy();
  }

  // ---------- controls ----------
  const dayInput = document.getElementById("day");
  dayInput.min = FIRST; dayInput.max = LAST;
  dayInput.addEventListener("change", () => { if (dayInput.value) { state.date = clamp(dayInput.value); render(); } });
  document.getElementById("prev").addEventListener("click", () => { state.date = clamp(addDays(state.date, -1)); render(); });
  document.getElementById("next").addEventListener("click", () => { state.date = clamp(addDays(state.date, 1)); render(); });
  document.getElementById("today").addEventListener("click", () => { state.date = LAST; render(); });
  document.getElementById("random").addEventListener("click", () => {
    const year = W.first_year + Math.floor(Math.random() * (Number(LAST.slice(0, 4)) - W.first_year + 1));
    const day = addDays(`${year}-03-01`, Math.floor(Math.random() * 107));      // March 1 to June 15
    state.date = clamp(day);
    state.site = HAY;
    render();
  });

  // Open a day directly with watch.html#2022-04-25, a day and site with #2024-05-13/albany,
  // or zoom the Hay River map with #2022-05-08/hay/60.856,-115.745,16 (lat,lon,zoom).
  const [h, siteId, view3] = decodeURIComponent(location.hash.slice(1)).split("/");
  if (/^\d{4}-\d{2}-\d{2}$/.test(h)) state.date = clamp(h);
  const pick = BLIND.find((s) => s.id === siteId);
  if (pick) state.site = pick;
  render();
  if (view3) {
    const [la, lo, zz] = view3.split(",").map(Number);
    if ([la, lo, zz].every(Number.isFinite)) zoom.setView([la, lo], zz);
  } else if (SINGLE && pick) {
    zoom.fitBounds(CANADA_BOUNDS);   // a blind-test site has no detail map: start on the summary
  }

  // Map explorer: share the map with explorer.js (tool buttons and legend).
  if (SINGLE) {
    window.HRFW.map = {
      map: zoom,
      home: () => zoom.flyToBounds([[view[1], view[0]], [view[3], view[2]]], { duration: 0.8 }),
      canada: () => zoom.flyToBounds(CANADA_BOUNDS, { duration: 0.8 }),
    };
  }
})();
