/* Hay River Breakup Watch - dashboard logic.
   Data comes from web/data/*.js (made by scripts/60_export_dashboard.py). */
(function () {
  "use strict";
  const H = window.HRFW;
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const C = () => ({
    ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), grid: css("--grid"), axis: css("--axis"),
    blue: css("--blue"), orange: css("--orange"), band: css("--band"), context: css("--context"),
    Low: css("--low"), Watch: css("--watch"), Warning: css("--warning"), Critical: css("--critical"),
  });

  const ICE = {
    1: { name: "open water", color: "#2a78d6" },
    2: { name: "smooth ice cover", color: "#1baf7a" },
    3: { name: "rough ice cover", color: "#4a3aa7" },
    4: { name: "new rubble / moving ice", color: "#eb6834" },
    11: { name: "open water (brightness only)", color: "#2a78d6", faded: true },
    12: { name: "smooth ice (brightness only)", color: "#1baf7a", faded: true },
    13: { name: "rough/rubble ice (brightness only)", color: "#eb6834", faded: true },
  };
  const ICONS = { Low: "✓", Watch: "⚠", Warning: "⚠", Critical: "⛔" };
  const LEVEL_TEXT = {
    Low: "Even the high end of the forecast stays below the lowest level at which flooding has been documented (166.4 m).",
    Watch: "The high end of the forecast reaches 166.4 m, the lowest level at which flooding has been documented. Keep watching.",
    Warning: "The most likely peak reaches 166.4 m, or the high end reaches 167.75 m (the 1985 and 1992 flood levels).",
    Critical: "The most likely peak is at or above 167.75 m, the level of the 1985 and 1992 floods.",
  };

  // ---------- helpers ----------
  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  const parse = (s) => new Date(s.slice(0, 10) + "T00:00:00Z");
  const fmtDate = (s, opts) => parse(s).toLocaleDateString("en-CA", Object.assign({ timeZone: "UTC", month: "short", day: "numeric" }, opts || {}));
  const addDays = (s, n) => { const d = parse(s); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---------- seasons ----------
  const forecastYears = Object.keys(H.forecasts).map(Number);
  const rcmYears = H.meta.rcm_years;
  const seasons = Array.from(new Set([...forecastYears, ...rcmYears])).sort((a, b) => b - a);
  const seasonSel = document.getElementById("season");
  seasons.forEach((y) => {
    const o = document.createElement("option");
    const tags = [];
    if (H.meta.flood_years.includes(y)) tags.push("flood");
    if (rcmYears.includes(y)) tags.push("RCM");
    if (!H.forecasts[y]) tags.push("ice only");
    o.value = y; o.textContent = y + (tags.length ? ` (${tags.join(", ")})` : "");
    seasonSel.appendChild(o);
  });

  const state = { season: 2022, days: [], i: 0, timer: null };

  function seasonDays(y) {
    const end = H.forecasts[y] ? `${y}-06-10` : `${y}-05-31`;
    const out = [];
    for (let s = `${y}-04-01`; s <= end; s = addDays(s, 1)) out.push(s);
    return out;
  }

  // ---------- map ----------
  const map = L.map("map", { zoomControl: true }).setView([60.79, -115.83], 11);
  // Esri light-grey basemap: OpenStreetMap's own tile servers block pages opened
  // straight from disk (file://), which showed "Access blocked" squares.
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 16, attribution: "Tiles &copy; Esri: Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
  }).addTo(map);
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 16,
  }).addTo(map);
  map.createPane("ice"); map.getPane("ice").style.zIndex = 420;
  map.createPane("flood"); map.getPane("flood").style.zIndex = 410;
  let iceLayer = null, floodLayer = null;

  L.polyline(H.map.jam_zone, { color: C().critical, weight: 3, dashArray: "6 6", opacity: 0.8 })
    .bindTooltip("Jam zone: lake to just past town (km 0-15)").addTo(map);
  H.map.km_marks.forEach(([lat, lon, km]) => {
    L.circleMarker([lat, lon], { radius: 4, color: C().ink2, weight: 1, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip(`km ${km} from Great Slave Lake`, { direction: "right" }).addTo(map);
  });
  H.map.gauges.forEach((g) => {
    L.circleMarker([g.lat, g.lon], { radius: 7, color: "#0b0b0b", weight: 2, fillColor: C().Watch, fillOpacity: 1 })
      .bindTooltip(`Gauge ${g.id}: ${esc(g.name)}`).addTo(map);
  });

  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const div = L.DomUtil.create("div", "map-legend");
    div.innerHTML = "<strong>RCM river ice</strong><br>" +
      [1, 2, 3, 4].map((k) => `<span class="swatch" style="background:${ICE[k].color}"></span>${ICE[k].name}`).join("<br>") +
      `<br><span class="swatch" style="background:${ICE[13].color};opacity:.45"></span>faded = brightness only (lower confidence)` +
      `<br><strong>Projected flood</strong><br><span class="swatch" style="background:#e87ba4;opacity:.75"></span>area flooded at forecast peak`;
    return div;
  };
  legend.addTo(map);

  // ---------- data lookups ----------
  function forecastFor(day) {
    const f = H.forecasts[state.season];
    return f ? f.series.find((r) => r.date === day) : null;
  }
  function sceneFor(day) {
    const from = addDays(day, -6);
    const list = H.scenes.filter((s) => s.year === state.season && s.time.slice(0, 10) <= day && s.time.slice(0, 10) >= from);
    if (!list.length) return null;
    list.sort((a, b) => (a.time < b.time ? -1 : 1));
    const last = list[list.length - 1].time.slice(0, 10);
    // Among the latest day's images, prefer the one that sees most of the jam zone.
    const sameDay = list.filter((s) => s.time.slice(0, 10) === last);
    sameDay.sort((a, b) => (b.jam_classified_pct || 0) - (a.jam_classified_pct || 0));
    return sameDay[0];
  }
  function floodFor(f) {
    if (!f) return null;
    const levels = H.flood.levels;
    const lv = Math.min(Math.max(Math.round(f.median * 2) / 2, levels[0]), levels[levels.length - 1]);
    const mouth = f.lake_high ? H.flood.mouths[1] : H.flood.mouths[0];
    const key = `${lv.toFixed(2)}|${mouth.toFixed(2)}`;
    return Object.assign({ level: lv, mouth, highLake: f.lake_high }, H.flood.layers[key]);
  }

  // ---------- cards ----------
  function driverText(d) {
    const v = d.value, e = d.effect_m;
    let what;
    if (d.name.startsWith("Great Slave")) what = `${Math.abs(v).toFixed(2)} m ${v >= 0 ? "above" : "below"} its long-term average`;
    else if (d.name.startsWith("Ice")) what = `about ${Math.round(v)} cm (estimated)`;
    else if (d.name.startsWith("Rise")) what = `${v >= 0 ? "up" : "down"} ${Math.abs(Math.round(v))} m³/s in the last 7 days`;
    else what = `${Math.round(v)} m³/s`;
    const dir = e >= 0 ? `<span class="up">raises</span>` : `<span class="down">lowers</span>`;
    return `<li><strong>${esc(d.name)}</strong>: ${what} &rarr; ${dir} the forecast by ${Math.abs(e).toFixed(1)} m</li>`;
  }

  function renderRisk(day, f, fl) {
    const body = document.getElementById("riskBody");
    const fy = H.forecasts[state.season];
    if (!f && fy && fy.peak_date && day > fy.series[fy.series.length - 1].date) {
      body.innerHTML = `<p><strong>Breakup peak has passed.</strong> The ${state.season} spring peak at the town gauge was
        ${fy.peak_level.toFixed(2)} m on ${fmtDate(fy.peak_date)}${fy.documented_flood ? " (documented flooding)" : ""}.
        The model forecasts the coming peak, so it stops a few days after it.</p>`;
      return;
    }
    if (!f) {
      body.innerHTML = fy
        ? `<p>No forecast for ${fmtDate(day)} (input data missing that day).</p>`
        : `<p><strong>No forecast for ${state.season}.</strong> River and lake gauge data for this spring are not yet in the
           Water Survey of Canada archive (HYDAT ends in 2024). The RCM ice map and ice-thickness charts are still shown.</p>`;
      return;
    }
    const changed = f.level !== f.model_level;
    let html = `<div><span class="badge lvl-${f.level}"><span class="icon">${ICONS[f.level]}</span>${f.level}</span></div>
      <p class="note">${LEVEL_TEXT[f.level]}</p>
      <dl class="kv">
        <dt>Forecast peak</dt><dd><span class="big">${f.median.toFixed(1)} m</span> above sea level</dd>
        <dt>Likely range</dt><dd>${f.p10.toFixed(1)} &ndash; ${f.p90.toFixed(1)} m (10&ndash;90%)</dd>
        ${f.observed != null ? `<dt>River today</dt><dd>${f.observed.toFixed(1)} m (daily average)</dd>` : ""}
      </dl>
      <div><strong>What is driving it</strong><ul class="drivers">${f.drivers.slice(0, 3).map(driverText).join("")}</ul></div>`;
    if (f.rcm_note) {
      html += `<p class="note"><strong>RCM:</strong> ${esc(f.rcm_note.replace(/^RCM: /, ""))}${changed
        ? `. Risk ${["Low", "Watch", "Warning", "Critical"].indexOf(f.level) > ["Low", "Watch", "Warning", "Critical"].indexOf(f.model_level) ? "raised" : "lowered"} from ${f.model_level}.` : "."}</p>`;
    }
    if (fl && fl.buildings != null) {
      const areas = Object.entries(fl.by_area || {}).sort((a, b) => b[1] - a[1]).slice(0, 3)
        .map(([k, v]) => `${esc(k)} ${v}`).join(", ");
      html += `<p class="note"><strong>If the river peaks at ${fl.level.toFixed(1)} m</strong> (with a ${fl.highLake ? "high" : "typical"} lake):
        about <strong>${fl.buildings}</strong> buildings and ${fl.road_km} km of road in the projected flood area${areas ? ` (${areas})` : ""}.</p>`;
    }
    if (fy.peak_level) {
      html += `<p class="note">What actually happened in ${state.season}: peak ${fy.peak_level.toFixed(2)} m on ${fmtDate(fy.peak_date)}${fy.documented_flood ? ", with <strong>documented flooding</strong>" : ""}.</p>`;
    }
    body.innerHTML = html;
  }

  function renderIce(day, sc) {
    const body = document.getElementById("iceBody");
    const prof = document.getElementById("profile");
    if (!sc) {
      body.innerHTML = rcmYears.includes(state.season)
        ? `<p>No RCM image of the river in the 6 days up to ${fmtDate(day)}.</p>`
        : `<p>No RCM images for ${state.season}: this dashboard uses RCM scenes from 2021 onward (RCM launched in June 2019).</p>`;
      prof.innerHTML = "";
      return;
    }
    const age = Math.round((parse(day) - parse(sc.time)) / 86400000);
    const pct = (v) => (v == null ? "n/a" : `${Math.round(v)}%`);
    body.innerHTML = `<p><strong>${fmtDate(sc.time, { year: "numeric" })} ${sc.time.slice(11)} UTC</strong>
      &middot; beam ${esc(sc.beam)} ${esc((sc.pass || "").toLowerCase())}${age > 0 ? ` &middot; ${age} day${age > 1 ? "s" : ""} old` : ""}</p>
      ${sc.late_winter ? `<p class="note">Late-winter image: shows the winter ice cover before melt.</p>` : ""}
      <dl class="kv">
        <dt>Jam zone, new rubble</dt><dd>${pct(sc.jam_new_rubble_pct)}</dd>
        <dt>Jam zone, open water</dt><dd>${pct(sc.jam_open_water_pct)}</dd>
        <dt>Jam zone, rough cover</dt><dd>${pct(sc.jam_rough_pct)}</dd>
        <dt>Bright ice (brightness only)</dt><dd>${pct(sc.jam_bright_v1_pct)}</dd>
        <dt>Jam zone compared with late winter</dt><dd>${pct(sc.jam_classified_pct)}</dd>
      </dl>`;
    const byKm = new Map(sc.profile.map(([k, c]) => [k, c]));
    let cells = "";
    for (let k = 0; k <= 55; k++) {
      const c = byKm.get(k);
      const info = c ? ICE[c] : null;
      cells += `<div title="km ${k}: ${info ? info.name : "not visible"}" style="background:${info ? info.color : "transparent"};${info && info.faded ? "opacity:.45" : ""}"></div>`;
    }
    prof.innerHTML = cells;
    prof.insertAdjacentHTML("afterend", "");
  }

  // ---------- charts ----------
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = C().ink2;
  const cursorPlugin = {
    id: "cursor",
    afterDatasetsDraw(chart, args, opts) {
      if (opts.index == null || opts.index < 0) return;
      const x = chart.scales.x.getPixelForValue(opts.index);
      const { top, bottom } = chart.chartArea, ctx = chart.ctx;
      ctx.save(); ctx.strokeStyle = C().ink; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke(); ctx.restore();
    },
  };
  const stripPlugin = {
    id: "riskStrip",
    afterDatasetsDraw(chart, args, opts) {
      if (!opts.levels) return;
      const { bottom, left, right } = chart.chartArea, ctx = chart.ctx, n = opts.levels.length;
      const w = (right - left) / Math.max(n - 1, 1);
      opts.levels.forEach((lv, i) => {
        ctx.fillStyle = C()[lv];
        ctx.fillRect(chart.scales.x.getPixelForValue(i) - w / 2, bottom - 8, w + 0.5, 8);
      });
    },
  };
  const baseOpts = () => ({
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { labels: { boxWidth: 12, filter: (it) => !it.text.startsWith("_") } } },
    scales: {
      x: { grid: { color: C().grid }, ticks: { maxTicksLimit: 10, color: C().muted } },
      y: { grid: { color: C().grid }, ticks: { color: C().muted } },
    },
  });
  let forecastChart, thickChart, tddChart;

  function buildForecastChart() {
    const f = H.forecasts[state.season];
    if (forecastChart) forecastChart.destroy();
    const ctx = document.getElementById("forecastChart");
    const col = C();
    if (!f) {
      forecastChart = new Chart(ctx, { type: "line", data: { labels: [], datasets: [] }, options: Object.assign(baseOpts(), {
        plugins: { title: { display: true, text: `No forecast for ${state.season} (gauge data not yet in HYDAT)`, color: col.ink2 } } }) });
      return;
    }
    const s = f.series;
    const labels = s.map((r) => fmtDate(r.date));
    const flat = (v) => s.map(() => v);
    const opts = baseOpts();
    opts.plugins.cursor = { index: -1 };
    opts.plugins.riskStrip = { levels: s.map((r) => r.level) };
    opts.plugins.tooltip = { callbacks: { label: (c) => c.dataset.label.startsWith("_") ? null : `${c.dataset.label}: ${c.parsed.y == null ? "n/a" : c.parsed.y.toFixed(2) + " m"}` } };
    opts.scales.y.title = { display: true, text: "m above sea level (town gauge)", color: col.muted };
    forecastChart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [
        { label: "_p10", data: s.map((r) => r.p10), borderWidth: 0, pointRadius: 0, fill: false },
        { label: "Forecast range (10-90%)", data: s.map((r) => r.p90), borderWidth: 0, pointRadius: 0, fill: "-1", backgroundColor: col.band },
        { label: "Forecast peak", data: s.map((r) => r.median), borderColor: col.blue, borderWidth: 2, pointRadius: 0 },
        { label: "Observed river level (daily)", data: s.map((r) => r.observed), borderColor: col.ink, borderWidth: 1.5, pointRadius: 0, spanGaps: true },
        { label: "Watch 166.4 m", data: flat(H.meta.watch_m), borderColor: col.Watch, borderWidth: 1, borderDash: [5, 4], pointRadius: 0 },
        { label: "Warning 167.75 m", data: flat(H.meta.warning_m), borderColor: col.Critical, borderWidth: 1, borderDash: [5, 4], pointRadius: 0 },
      ].concat(f.peak_level ? [{ label: `Actual peak ${f.peak_level.toFixed(2)} m`, data: flat(f.peak_level), borderColor: col.muted, borderWidth: 1, borderDash: [2, 3], pointRadius: 0 }] : []) },
      options: opts,
      plugins: [cursorPlugin, stripPlugin],
    });
  }

  function buildThickChart() {
    if (thickChart) thickChart.destroy();
    const col = C();
    const S = H.seasons.seasons[state.season];
    const band = H.seasons.thickness_band;
    const n = band.p50.length;
    const start = parse(`${state.season - 1}-09-01`);
    const labels = Array.from({ length: n }, (_, i) => { const d = new Date(start); d.setUTCDate(d.getUTCDate() + i); return d.toLocaleDateString("en-CA", { timeZone: "UTC", month: "short", day: "numeric" }); });
    const opts = baseOpts();
    opts.scales.y.title = { display: true, text: "cm", color: col.muted };
    opts.plugins.tooltip = { callbacks: { label: (c) => c.dataset.label.startsWith("_") ? null : `${c.dataset.label}: ${c.parsed.y == null ? "n/a" : c.parsed.y.toFixed(0) + " cm"}` } };
    thickChart = new Chart(document.getElementById("thickChart"), {
      type: "line",
      data: { labels, datasets: [
        { label: "_all10", data: band.p10, borderWidth: 0, pointRadius: 0, fill: false },
        { label: "All winters (10-90%)", data: band.p90, borderWidth: 0, pointRadius: 0, fill: "-1", backgroundColor: col.context },
        { label: "Typical winter", data: band.p50, borderColor: col.muted, borderWidth: 1.5, pointRadius: 0 },
        { label: "_low", data: S ? S.thickness_low.slice(0, n) : [], borderWidth: 0, pointRadius: 0, fill: false },
        { label: "_high", data: S ? S.thickness_high.slice(0, n) : [], borderWidth: 0, pointRadius: 0, fill: "-1", backgroundColor: col.band },
        { label: `Winter ${state.season - 1}-${state.season}`, data: S ? S.thickness.slice(0, n) : [], borderColor: col.blue, borderWidth: 2, pointRadius: 0 },
      ] },
      options: opts,
    });
  }

  function buildTddChart() {
    if (tddChart) tddChart.destroy();
    const col = C();
    const S = H.seasons.seasons[state.season];
    const band = H.seasons.tdd_band;
    const n = band.p50.length;
    const jan1 = parse(`${state.season}-01-01`);
    const labels = Array.from({ length: n }, (_, i) => { const d = new Date(jan1); d.setUTCDate(d.getUTCDate() + band.doy0 - 1 + i); return d.toLocaleDateString("en-CA", { timeZone: "UTC", month: "short", day: "numeric" }); });
    const own = Array(n).fill(null);
    if (S && S.tdd_doy0) S.tdd.forEach((v, i) => { const j = S.tdd_doy0 - band.doy0 + i; if (j >= 0 && j < n) own[j] = v; });
    const opts = baseOpts();
    opts.plugins.cursor = { index: -1 };
    opts.scales.y.title = { display: true, text: "degree-days (°C·day)", color: col.muted };
    opts.plugins.tooltip = { callbacks: { label: (c) => c.dataset.label.startsWith("_") ? null : `${c.dataset.label}: ${c.parsed.y == null ? "n/a" : c.parsed.y.toFixed(0)}` } };
    tddChart = new Chart(document.getElementById("tddChart"), {
      type: "line",
      data: { labels, datasets: [
        { label: "_p10", data: band.p10, borderWidth: 0, pointRadius: 0, fill: false },
        { label: "All springs (10-90%)", data: band.p90, borderWidth: 0, pointRadius: 0, fill: "-1", backgroundColor: col.context },
        { label: "Typical spring", data: band.p50, borderColor: col.muted, borderWidth: 1.5, pointRadius: 0 },
        { label: `Spring ${state.season}`, data: own, borderColor: col.blue, borderWidth: 2, pointRadius: 0 },
      ] },
      options: opts,
      plugins: [cursorPlugin],
    });
    tddChart.$doy0 = band.doy0;
  }

  // ---------- update ----------
  function setCursor(day) {
    if (forecastChart && H.forecasts[state.season]) {
      forecastChart.options.plugins.cursor.index = H.forecasts[state.season].series.findIndex((r) => r.date === day);
      forecastChart.update("none");
    }
    if (tddChart) {
      const d = parse(day), jan1 = parse(`${state.season}-01-01`);
      tddChart.options.plugins.cursor.index = Math.round((d - jan1) / 86400000) + 1 - tddChart.$doy0;
      tddChart.update("none");
    }
  }

  function update() {
    const day = state.days[state.i];
    document.getElementById("dayLabel").textContent = fmtDate(day, { weekday: "short", year: "numeric" });
    const f = forecastFor(day);
    const sc = sceneFor(day);
    const fl = floodFor(f);

    if (iceLayer) { map.removeLayer(iceLayer); iceLayer = null; }
    if (sc && document.getElementById("showIce").checked) {
      iceLayer = L.imageOverlay("../" + sc.img, sc.bounds, { pane: "ice", interactive: false }).addTo(map);
    }
    if (floodLayer) { map.removeLayer(floodLayer); floodLayer = null; }
    if (fl && fl.img && document.getElementById("showFlood").checked) {
      floodLayer = L.imageOverlay("../" + fl.img, fl.bounds, { pane: "flood", opacity: 0.75, interactive: false }).addTo(map);
    }
    renderRisk(day, f, fl);
    renderIce(day, sc);
    setCursor(day);
  }

  function loadSeason(y, dayIso) {
    state.season = Number(y);
    seasonSel.value = String(y);
    state.days = seasonDays(state.season);
    const slider = document.getElementById("day");
    slider.max = state.days.length - 1;
    const want = dayIso || `${state.season}-05-01`;
    state.i = Math.max(0, state.days.indexOf(want));
    slider.value = state.i;
    buildForecastChart(); buildThickChart(); buildTddChart();
    update();
  }

  // ---------- controls ----------
  seasonSel.addEventListener("change", () => { stop(); loadSeason(seasonSel.value); });
  document.getElementById("day").addEventListener("input", (e) => { state.i = Number(e.target.value); update(); });
  document.getElementById("showIce").addEventListener("change", update);
  document.getElementById("showFlood").addEventListener("change", update);
  const playBtn = document.getElementById("play");
  function stop() { if (state.timer) { clearInterval(state.timer); state.timer = null; playBtn.innerHTML = "&#9654; Play"; } }
  function play() {
    stop();
    playBtn.innerHTML = "&#10074;&#10074; Pause";
    state.timer = setInterval(() => {
      if (state.i >= state.days.length - 1) { stop(); return; }
      state.i += 1; document.getElementById("day").value = state.i; update();
    }, 450);
  }
  playBtn.addEventListener("click", () => (state.timer ? stop() : play()));
  document.getElementById("replay2022").addEventListener("click", () => {
    loadSeason(2022, "2022-04-25");
    map.setView([60.82, -115.79], 12);
    play();
  });

  // ---------- about ----------
  function renderAbout() {
    const m = H.meta;
    const skill = m.skill.map((r) => `<tr><td>${r.days_before_peak}</td><td>${r.MAE_model.toFixed(2)} m</td><td>${r.MAE_upstream.toFixed(2)} m</td><td>${r.MAE_climatology.toFixed(2)} m</td></tr>`).join("");
    const v = m.validation_2022.map((r) => `<li>${esc(r.compared_with)}: the projection covers ${Math.round(r.share_of_observed_inside_projection * 100)}% of the flooding it shows.</li>`).join("");
    document.getElementById("about").innerHTML = `
      <p><strong>1. River ice from RCM.</strong> Every RCM image (16 m beams, HH+HV) of the 55 km river corridor is calibrated, corrected for viewing angle,
      and compared with a late-winter image taken from the same direction. Pixels that got much brighter = <em>new rubble / moving ice</em> (jams);
      much darker after melt began = <em>open water</em>; unchanged = the winter ice cover (smooth or rough). Where no matching late-winter image exists,
      the class comes from brightness alone and is shown faded (lower confidence). The jam zone is km 0&ndash;15: Great Slave Lake up past the town.</p>
      <p><strong>2. Ice thickness</strong> is estimated from Hay River air temperatures (ECCC, 1943&ndash;today) with Stefan's equation
      (thickness = 1.5 &times; &radic;freezing degree-days). It is an approximation, not a measurement.</p>
      <p><strong>3. Breakup risk.</strong> A simple linear model forecasts the spring peak level at gauge 07OB001 from upstream flow (Meander River),
      its 7-day rise, Great Slave Lake level and ice thickness, trained on 46 springs (1976&ndash;2024) with peak levels from the GNWT (2025) flood
      hazard study. Every spring shown was forecast by a model that never saw it. RCM moves the risk up one level when rubble ice builds up in the
      jam zone during melt, and down one level once the jam zone is mostly open water.</p>
      <div class="tablewrap"><table><tr><th>Days before peak</th><th>Model error</th><th>Upstream flow only</th><th>Long-term average</th></tr>${skill}</table></div>
      <p><strong>4. Projected flooding.</strong> The forecast level is turned into a flood map with the 2020 lidar ground model, using height above the
      nearest river channel and an ice-jam water surface sloping from the gauge down to the lake. Its shape was tuned to 2022 (~500 homes and 70 businesses damaged).</p>
      <ul>${v}</ul>
      <p><strong>Limitations.</strong> Few flood years exist, so accuracy claims are modest: 7 days before the peak the model rated all 5 tested flood springs
      Warning or higher, but also rated about 1 in 3 normal springs Warning. Gauge level alone does not decide flooding: where the ice jams matters
      (1989, 1994 and 2021 peaked above 168 m without documented flooding). RCM cannot tell smooth ice from calm water, and the flood map likely
      overestimates flooding in flat forest far from the river. Documented flood years: ${m.flood_years.join(", ")}.</p>`;
  }

  renderAbout();
  // Open a chosen spring with index.html#2024 or index.html#2024-04-20.
  const hash = decodeURIComponent(location.hash.slice(1));
  const hashYear = Number(hash.slice(0, 4));
  if (seasons.includes(hashYear)) loadSeason(hashYear, hash.length === 10 ? hash : undefined);
  else loadSeason(2022, "2022-05-08");
})();
