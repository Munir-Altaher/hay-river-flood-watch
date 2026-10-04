/* Hay River Breakup Watch - simplified demo (data from scripts/61_export_demo.py). */
(function () {
  "use strict";
  const D = window.HRFW.demo;
  const ICONS = { Low: "✓", Watch: "⚠", Warning: "⚠", Critical: "⛔" };
  const STAGE_NAMES = { before: "before peak", peak: "peak", after: "after peak" };

  const fmt = (iso, withYear) => new Date(iso + "T12:00:00Z").toLocaleDateString("en-CA",
    Object.assign({ timeZone: "UTC", month: "short", day: "numeric" }, withYear ? { year: "numeric" } : {}));
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---------- maps ----------
  // Esri light-grey basemap: OpenStreetMap's own tile servers block pages opened
  // straight from disk (file://), which is why the old map showed "Access blocked".
  const BASE = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
  const bounds = L.latLngBounds(D.view.bounds);
  const maps = {}, layers = {};
  let syncing = false;

  [2022, 2023].forEach((year) => {
    document.getElementById(`title${year}`).textContent = D.years[year].title;
    const m = L.map(`map${year}`, {
      center: D.view.center, zoom: D.view.zoom, minZoom: 11, maxZoom: 15,
      maxBounds: bounds.pad(0.25), zoomSnap: 0.5, attributionControl: year === 2023,
    });
    L.tileLayer(BASE + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 16, attribution: "Tiles &copy; Esri",
    }).addTo(m);
    m.createPane("flood").style.zIndex = 410;
    m.createPane("ice").style.zIndex = 420;
    m.createPane("labels").style.zIndex = 430;
    m.getPane("labels").style.pointerEvents = "none";
    L.tileLayer(BASE + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 16, pane: "labels",
    }).addTo(m);
    m.fitBounds(bounds);
    maps[year] = m;
    layers[year] = { ice: null, flood: null };
  });

  // Keep both maps showing the same place.
  [[2022, 2023], [2023, 2022]].forEach(([a, b]) => {
    maps[a].on("move zoom", () => {
      if (syncing) return;
      syncing = true;
      maps[b].setView(maps[a].getCenter(), maps[a].getZoom(), { animate: false });
      syncing = false;
    });
  });

  function showStage(stage) {
    document.querySelectorAll(".stages button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.stage === stage)));
    [2022, 2023].forEach((year) => {
      const s = D.years[year].stages[stage];
      const m = maps[year], l = layers[year];
      if (l.flood) m.removeLayer(l.flood);
      if (l.ice) m.removeLayer(l.ice);
      l.flood = L.imageOverlay(s.flood_img, s.flood_bounds, { pane: "flood", interactive: false }).addTo(m);
      l.ice = L.imageOverlay(s.ice_img, s.ice_bounds, { pane: "ice", interactive: false }).addTo(m);
      const rel = s.days_from_peak === 0 ? "peak day"
        : `${Math.abs(s.days_from_peak)} day${Math.abs(s.days_from_peak) > 1 ? "s" : ""} ${s.days_from_peak < 0 ? "before" : "after"} peak`;
      document.getElementById(`cap${year}`).innerHTML =
        `<strong>${fmt(s.date, true)}</strong> &middot; ${rel} &middot; river at town ${s.river_level_m.toFixed(1)} m` +
        (s.buildings_flooded ? ` &middot; ~${s.buildings_flooded} buildings in flood area` : "");
    });
    document.getElementById("see").innerHTML = D.see[stage].map((p) => `<li>${esc(p)}</li>`).join("");
    document.getElementById("seeTitle").textContent = `What we see: ${STAGE_NAMES[stage]}`;
  }
  document.querySelectorAll(".stages button").forEach((b) =>
    b.addEventListener("click", () => showStage(b.dataset.stage)));

  // ---------- prediction ----------
  const datesEl = document.getElementById("dates");
  D.predictions.forEach((p, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = `${fmt(p.date, true)}<small>${p.year === 2023 ? "control year" : "flood year"}</small>`;
    b.addEventListener("click", () => showPrediction(i));
    datesEl.appendChild(b);
  });

  function showPrediction(i) {
    const p = D.predictions[i];
    datesEl.querySelectorAll("button").forEach((b, j) => b.setAttribute("aria-pressed", String(i === j)));
    document.getElementById("result").innerHTML = `
      <span class="badge ${p.level}"><span aria-hidden="true">${ICONS[p.level]}</span>${p.level}</span>
      <div class="conf">
        <p class="conf-text"><strong>${p.confidence_text}</strong> chance the spring peak reaches flood level (${D.flood_level_m} m)</p>
        <div class="bar" role="img" aria-label="${p.confidence}%"><span style="width:${Math.min(p.confidence, 100)}%"></span></div>
      </div>
      <p class="reason">${esc(p.reason)}</p>`;
  }

  showStage("peak");
  showPrediction(2);
})();
