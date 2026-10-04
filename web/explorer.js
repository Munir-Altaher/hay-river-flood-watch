// Map explorer: tool buttons and legend for the single map. Everything else (forecast,
// places, map layers) is the user view's own code in watch.js, run in single-map mode.
(function () {
  "use strict";
  const M = window.HRFW.map;
  const map = M.map;
  const $ = (id) => document.getElementById(id);

  $("zoomIn").addEventListener("click", () => map.zoomIn(1));
  $("zoomOut").addEventListener("click", () => map.zoomOut(1));
  $("home").addEventListener("click", M.home);
  $("allSites").addEventListener("click", M.canada);
  const showLegend = (on) => {
    $("legend").hidden = !on;
    $("legendBtn").setAttribute("aria-expanded", String(on));
  };
  $("legendBtn").addEventListener("click", () => showLegend($("legend").hidden));
  if (window.innerWidth < 820) showLegend(false);   // small screens: keep the map clear
  $("fullBtn").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen();
  });
  document.addEventListener("fullscreenchange", () => setTimeout(() => map.invalidateSize(), 100));
})();
