/* Blind test section of the judges' demo (data from scripts/76_export_blind_web.py). */
(function () {
  "use strict";
  const B = window.HRFW.blind;
  const ORDER = ["hay_river", "fort_simpson", "albany"];
  const ICONS = { Low: "✓", Watch: "⚠", Warning: "⚠", Critical: "⛔" };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const md = (s) => new Date(`2001-${s}T12:00:00Z`).toLocaleDateString("en-CA", { timeZone: "UTC", month: "short", day: "numeric" });
  const state = { site: "fort_simpson", year: null };

  const sitesEl = document.getElementById("blindSites");
  ORDER.forEach((id) => {
    const s = B.sites[id];
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.site = id;
    b.innerHTML = `${esc(s.name)}<small>${esc(s.role === "Training site" ? "training site" : "blind test")}</small>`;
    b.addEventListener("click", () => { state.site = id; state.year = null; render(); });
    sitesEl.appendChild(b);
  });

  function chart(row) {
    // Jam-zone rubble % in every usable image that spring, with the 83.7% line.
    const W = 760, H = 220, L = 44, R = 12, T = 14, Bm = 30;
    const start = Date.UTC(2001, 2, 15), end = Date.UTC(2001, 5, 20);
    const x = (m) => L + ((Date.parse(`2001-${m}T00:00:00Z`) - start) / (end - start)) * (W - L - R);
    const y = (v) => T + (1 - v / 100) * (H - T - Bm);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Rubble ice in the jam zone, spring ${row.year}">`;
    [0, 50, 100].forEach((v) => {
      svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#dfe3e8"/>` +
             `<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="#5d6b79">${v}%</text>`;
    });
    ["03-15", "04-01", "04-15", "05-01", "05-15", "06-01", "06-15"].forEach((m) => {
      svg += `<text x="${x(m)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="#5d6b79">${md(m)}</text>`;
    });
    const th = B.rules.threshold;
    svg += `<line x1="${L}" x2="${W - R}" y1="${y(th)}" y2="${y(th)}" stroke="#eb2d37" stroke-dasharray="6 4" stroke-width="1.5"/>` +
           `<text x="${W - R}" y="${y(th) - 5}" text-anchor="end" font-size="11" fill="#a3161d">jam threshold ${th}%</text>`;
    if (row.cleared) {
      svg += `<line x1="${x(row.cleared)}" x2="${x(row.cleared)}" y1="${T}" y2="${H - Bm}" stroke="#1f6fbf" stroke-dasharray="3 3"/>` +
             `<text x="${x(row.cleared) + 4}" y="${T + 10}" font-size="11" fill="#1f6fbf">ice cleared</text>`;
    }
    row.images.forEach(([m, rubble, melt]) => {
      if (rubble == null) return;
      const fill = melt ? (rubble >= th ? "#f2a900" : "#26374a") : "#ffffff";
      svg += `<circle cx="${x(m)}" cy="${y(rubble)}" r="5.5" fill="${fill}" stroke="#26374a" stroke-width="1.5">` +
             `<title>${md(m)}: ${rubble}% rubble ice${melt ? "" : " (before melt)"}</title></circle>`;
    });
    svg += "</svg>";
    return svg + `<p>Each dot is one RCM image: rubble ice in the river near the community. ` +
      `Hollow = before melt (not counted). Amber = above the jam threshold during melt.</p>`;
  }

  function render() {
    const s = B.sites[state.site];
    sitesEl.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.site === state.site)));
    document.getElementById("blindSite").innerHTML =
      `<strong>${esc(s.where)}</strong> &middot; ${esc(s.role)} &middot; images: ${esc(s.images)}`;
    const rows = s.years;
    if (state.year == null) {
      const top = rows.filter((r) => r.level === "Critical" || r.level === "Warning");
      state.year = (top[0] || rows[0]).year;
    }
    document.getElementById("blindTable").innerHTML =
      `<thead><tr><th>Spring</th><th>Risk</th><th>Likelihood</th><th>Confidence</th><th>What the images show</th><th>Outcome</th></tr></thead><tbody>` +
      rows.map((r) => `<tr data-year="${r.year}" aria-selected="${r.year === state.year}" tabindex="0">
        <td><strong>${r.year}</strong>${!r.main && state.site !== "hay_river" ? '<br><span class="chip-sep">separate, 100 m</span>' : ""}</td>
        <td><span class="badge sm ${ICONS[r.level] ? r.level : "None"}">${ICONS[r.level] ? ICONS[r.level] + " " : ""}${esc(r.level)}</span></td>
        <td>${r.likelihood == null ? "n/a" : r.likelihood + "%"}</td>
        <td>${esc(r.confidence)}</td>
        <td>${esc(r.why)}</td>
        <td class="${r.outcome === "Not checked yet" ? "outcome-pending" : ""}">${esc(r.outcome)}</td></tr>`).join("") + "</tbody>";
    document.querySelectorAll("#blindTable tbody tr").forEach((tr) => {
      const pick = () => { state.year = Number(tr.dataset.year); render(); };
      tr.addEventListener("click", pick);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    });
    const row = rows.find((r) => r.year === state.year);
    document.getElementById("blindChart").innerHTML =
      `<p><strong>Spring ${row.year}</strong>${row.flags && row.flags !== "none" ? ` &middot; lower confidence because: ${esc(row.flags)}` : ""}</p>` + chart(row);
    const lock = B.locks.find((l) => l.file.includes(state.site === "albany" ? "albany" : "fort_simpson"));
    document.getElementById("blindLock").innerHTML =
      `Rules locked ${B.rules.utc} (SHA-256 ${B.rules.sha256.slice(0, 16)}...). ` +
      `Predictions locked ${lock.utc} (SHA-256 ${lock.sha256.slice(0, 16)}...). Likelihood is the share of melt-season images above the threshold, not a calibrated probability.`;
  }
  render();
})();
