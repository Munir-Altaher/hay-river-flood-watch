# Hay River Flood Watch — Hackathon Project (Challenge 3)

## Goal
Assess river ice conditions on the Hay River (NWT) and predict whether spring
breakup could raise water levels enough to flood the town. **Using RCM
(RADARSAT Constellation Mission) data from EODMS is a hackathon requirement**
and it must stay the core of the analysis; gauge, climate and DEM data
support it, they don't replace it.
Main validation event: the May 2022 ice-jam flood (peak ~May 11–13;
whole-town evacuation May 11).

## Background
Hay River floods are ice-jam floods. At breakup, ice breaks up and jams near
the river mouth and the East/West channels around Vale Island, while
snowmelt from upstream raises flow; water backs up behind the jam. Risk
depends on: ice thickness/strength, where ice is jamming, and how fast
upstream discharge is rising.

## System (4 parts)
1. **Ice mapping from RCM**
   - River corridor from the mouth upstream at least 40–50 km. River mask
     from NRCan hydrography (CanVec / National Hydro Network) or
     OpenStreetMap — not a hand-drawn box.
   - Classify river pixels in each spring scene: open water, smooth sheet
     ice, rough/rubble (jammed) ice. Features: HH/HV dB, ratio, texture.
     Rule-based first, random forest if we have labels.
   - Output an "ice profile" per date: ice class vs. km from the mouth.
2. **Ice thickness estimate**
   - Daily temperatures for Hay River from ECCC historical climate data.
   - Accumulated freezing degree-days (AFDD) per winter; Stefan's equation
     thickness = alpha * sqrt(AFDD). alpha is a documented, adjustable
     parameter; this is an approximation.
   - Spring thawing degree-days (TDD) to track melt progress.
3. **Breakup flood risk model**
   - HYDAT daily water level and discharge: gauge near town + upstream
     gauges (station IDs to be confirmed with the user). Note HYDAT
     ice-affected / backwater flags.
   - One row per year over the full gauge + climate record: winter ice
     thickness, spring thaw rate, upstream discharge and its rate of rise
     around breakup, resulting spring peak water level at town; flag known
     flood years.
   - Simple, explainable model for spring peak level (and/or flood vs. not).
     Leave-one-year-out validation. Few flood years: don't overclaim,
     report uncertainty. Baseline: peak level from upstream discharge alone.
   - Current-conditions view combines the forecast with the latest RCM ice
     profile (rubble ice near the mouth/channels raises risk).
4. **Predicted water level → flood map**
   - Forecast level → projected flood extent via HAND (height above nearest
     drainage) from a DEM, keeping only areas connected to the river.
   - Validate against the RCM-derived May 2022 flood map.
   - Intersect with OpenStreetMap buildings/roads for impact estimates.

## Dashboard
- River-corridor map of RCM ice classes by date (date slider).
- Ice thickness and degree-day charts for the selected winter.
- Forecast panel: predicted peak level with uncertainty range; risk level
  (Low / Watch / Warning / Critical) with plain-language drivers.
- Projected flood map + impact counts for the forecast level.
- Replay mode for spring 2022: day-by-day risk rating leading up to the flood.

## Build order (check in with the user after each)
0. Data availability check (RCM scenes over corridor, HYDAT stations and
   record lengths, climate station record) — report before building.
1. Data download and preparation
2. Ice thickness and degree-days
3. Ice mapping from RCM
4. Risk model
5. Flood extent projection
6. Dashboard

## Data decisions (confirmed with user)
- Gauges: 07OB001 town (level 2002–2024, assumed datum; discharge 1963–2024,
  breakup flows mostly flagged "Ice Conditions"), upstream 07OB003 (Meander
  River, discharge 1974–2024) and 07OB008 (Alta/NWT border, spring discharge
  2017–2023), lake 07OB002. Source: api.weather.gc.ca hydrometric-daily-mean.
- Risk-model target: spring peak water level at 07OB001, 2002–2024.
- Known flood years (confirmed by user): the GNWT 2025 flood hazard summary
  report list (data/raw/docs/) — 1951, 1963, 1974, 1985, 1992, 2003, 2008,
  2022 (replaced the earlier 1963/1985/2008/2022 list).
- Risk settings: keep the cautious thresholds (catch floods, accept ~1/3
  normal years at Warning) — confirmed by user.
- Breakup peak levels: GNWT report Table 16, instantaneous peaks at 07OB001
  1964–2023 in m above sea level (GSC local 1985 adj ≈ CGVD28). HYDAT daily
  "assumed datum" + ~158.27 m ≈ sea level (±0.5 m).
- Climate: Hay River A 2202400 (1943–2014) + 2202401 (2014–), gaps from
  2202402/2202403.
- DEM: NRCan HRDEM lidar 2020 (1 m) covers all of town; MRDEM 30 m upstream.
- River km 0 = where the East Channel meets Great Slave Lake; distances
  run upstream along East Channel + main river.

## New pipeline scripts (10+)
- 10_river_corridor.py → data/processed/corridor/corridor.gpkg (centreline,
  km_marks, river_mask, corridor, channel_lines) from OSM.
- 11_search_rcm_corridor.py → outputs/rcm_corridor_scenes.csv (EODMS
  catalogue search, springs 2020–2026, river km covered per scene).
- 12_get_gauges.py → data/raw/hydat/<station>_daily.csv
- 13_get_climate.py → data/raw/climate/hay_river_daily.csv (merged stations)
- 14_get_dem.py → data/raw/dem/dem_town_5m.tif, dem_corridor_30m.tif

- 15_order_rcm.py (list | order | download) → data/rcm/corridor/
- 20_ice_thickness.py → data/processed/ice/ (Stefan alpha 1.5, range 1.2–1.9)
- rcm_utils.py (shared RCM reader), 30_corridor_scenes.py (16M scenes on
  corridor grid + river_pixels.tif), 31_ice_classes.py (v1 brightness rules),
  32_ice_change.py (v2 change since late winter; dashboard uses v2 with v1
  fallback marked lower confidence)
- 40_breakup_history.py (GNWT Table 16 → data/processed/risk/breakup_history.csv),
  41_risk_model.py (ridge on q_up, q_up_rise7, lake_anom, thickness_cm;
  leave-one-year-out; risk levels Watch ≥166.4 m, Warning ≥167.75 m; RCM
  adjusts ±1 level; 2022 replay)

- 50_flood_projection.py: HAND on 5 m lidar with a sloping ice-jam water
  surface (mouth level → gauge level, exponent 0.6 chosen to match ~570
  homes/businesses damaged in 2022); Great Slave Lake masked as permanent
  water; impact curves for mouth 157.0 and 158.18 m →
  data/processed/flood_projection/impact_curve.csv

- 60_export_dashboard.py → web/data/*.js + web/data/img/*.png (data as JS so
  the pages work from file://). Full analysis dashboard (hidden, kept):
  web/full/index.html (#2024 or #2022-05-08 opens a given spring/day).
- 61_export_demo.py → web/data/demo.js + demo_*.png. JUDGES' PAGE "How the model
  works" = web/how-it-works.html (moved from index.html; NEVER remove it; linked
  from the explorer and the user view) (demo.js, demo.css): 2022 flood (positive control) vs 2023 no flood
  (negative control), stages before/peak/after (2022: May 8/12/16 16M4 desc;
  2023: Apr 24/28/May 2 16M8 desc), v1 ice classes for both, estimated
  flooded land shown only within 1.5 km of water and when river ≥ 166.4 m,
  5 prediction dates. CSA-inspired colours (#26374A, #F5F6F8, #EB2D37).
- Basemap: Esri World Light Gray (OSM tiles return "Access blocked" for
  file:// pages — that was the map bug).
- RCM risk rule: jam-zone rough/rubble % threshold set halfway between 2022
  and 2023 (83.7%, saved in data/processed/risk/rcm_threshold.txt); the v2
  "new rubble" raise rule is off. Checked on 2021 (4/6 above) and 2024 (0/11).
- USER VIEW (page 2) = web/watch.html (watch.js, watch.css): "Breakup Watch
  Canada" time machine. 16_get_gauges_recent.py downloads 2025-2026
  provisional gauge data (Water Office real-time CSV, ~18 months kept);
  62_export_watch.py → web/data/watch.js + w_*.png: for every day Jan 1 to
  Jun 30, 1976-2026: risk (LOYO model for ≤2024, final model for 2025-26),
  chance of reaching 166.4 m, RCM evidence, breakup danger window (replay of
  other springs' thaw to reach 49/59/87 TDD; real peak inside the 25-75%
  window in 15/21 springs from Apr 1, 17/21 from Apr 15), breakup-over rule.
  Outlook starts Mar 1 (upstream gauge 07OB003 is off Dec-Feb).
  Other Canadian sites on the map are SIMULATED in watch.js (user chose this;
  always labelled "Simulated example"). watch.html#2022-04-25 opens a day.
- No em dashes in any web text (user request).
- FIRST-RESPONDER features in the user view (watch.html): dates limited to 2021+
  (RCM era; 62_export_watch.py FIRST_YEAR=2021); "How the AI made this decision"
  bullets + "Show full analysis" (built in watch.js from per-day fields: base,
  all factor contributions, p10/p90, RCM, window, skill); "Places that may be
  affected" from 63_places.py → web/data/places.js (OSM facilities, neighbourhoods,
  main roads/bridges; first-flood level per place from the flood-projection model
  at 0.1 m steps, typical and high lake; roads exclude river crossings, bridges use
  approach roads; floor 166.4 m = lowest documented flood level). Place chance =
  share of past forecast errors (resid_q) putting the peak at/above the place's
  level; High danger ≥50%, Possible ≥10%; place confidence capped at Medium.
- Zoomed map (watch.js): Esri World Street Map base (road names) with layer
  switch to light grey / satellite; OSM buildings from 63_places.py →
  web/data/buildings.js (each with flood level, coloured by daily chance, drawn on
  a canvas renderer); facility letter icons (H, S, F, P, C, A, G) with name labels
  from zoom 14. #date/hay/lat,lon,zoom opens a map view.
- Refresh order: 16 → 30 → 31 → 32 → 41 → 50 → 60 → 61 → 62 → 63 (63 reuses cached
  first_flood_level_*.tif; delete them if script 50 changes).
- BLIND TEST (Fort Simpson NT, Albany River estuary ON), outputs in
  outputs/blind_test/: 70_blind_order.py (order/download), 71_blind_sites_setup.py
  (jam zone rule: connected channels from 5 km below the community or the mouth
  to 5 km above it; community = 5th-95th pct of OSM buildings along river),
  72_blind_climate.py (ECCC temps, co-located stations merged), 73_blind_preprocess.py
  (Hay River preprocessing, deletes zips), 74_blind_lock_rules.py (locked_rules_*.json),
  75_blind_predict.py (RCM-only yearly score, locked + lock_register.txt),
  76_export_blind_web.py (verifies fingerprints → web/data/blind.js).
  Rules: never look up outcomes/news/gauges for blind sites; do not change locked
  files; evaluation only when the user asks. Albany 2025-26 = 100 m, separate.
  Web: page 1 "Blind test" section (web/blindtest.js); page 2 shows the two sites
  as "Blind test site" markers (watch.html#2024-05-13/albany).
- Refresh order after new data: 16 → 30 → 31 → 32 → 41 → 50 → 60 → 61 → 62 → 63.
- MAP EXPLORER (front page) = web/index.html (explorer.js, explorer.css). REWORKED
  2026-10-04 at user request: it must show EXACTLY the user view's information,
  just laid out differently. Left panel = day picker, site detail card, "How the AI
  made this decision" + full analysis, "Places that may be affected". ONE map: the
  user view's Hay River places map (buildings, facilities, ice, flood); zoomed out
  (< zoom 10) it shows the Canada summary dots + warning legend instead. Built by
  running watch.js in single-map mode (SINGLE = no #canada element; exposes
  window.HRFW.map for explorer.js tool buttons), so both pages share one code path.
  Same address format as watch.html (#date/site/lat,lon,zoom). The earlier dark
  "Copernicus-style" explorer data (65_export_explorer.py → web/data/explorer.js,
  x_*.png) is no longer used by any page.
  MAP COLOURS (user view + explorer; one meaning per colour, legend grouped in
  watch.css .lg-*): ice from 62_export_watch.py ICE_COLOURS = open water #1f6fbf,
  smooth ice #aedcf0, rubble #7b3fbf (purple); flooded land teal (0,150,170) at
  45% opacity; risk red/yellow/green only for buildings, place dots and facility
  rings; grey #d5dae0 = building not at risk, #9aa5b1 = no prediction. Site
  outline: Hay River thin solid, blind thick solid, simulated dashed. The judges'
  page keeps its own palette (61_export_demo.py). Logo: original side-by-side, NO
  tagline under it.
  A full Canada.ca colour scheme was tried on 2026-10-04 and the user asked to revert
  it: keep the current palette (risk green #2e7d4f / yellow #f2b705 / red #eb2d37).
  SPEED (2026-10-04): 62 pictures at ICE_PIXEL_M 20 / FLOOD_PIXEL_M 16 web-map metres
  (~10 m / ~8 m on the ground; were 8 = ~4 m); watch.js keeps an unchanged picture and
  swaps new ones only after they load (setOverlay), restyles only buildings whose colour
  changed, removes buildings from the explorer map below zoom 10, wheel zoom
  wheelPxPerZoomLevel 45 (~1 level per notch; user wanted bigger steps than 110),
  tiles keepBuffer 4 / updateWhenZooming false. Brand "Polaris Lifeline" (user's logos in
  app/assets/logos; copies with only empty margin trimmed in web/assets; never
  edit/recolour logos; no CSA/GC logos or branding). Theme: navy #26374A, map
  #0B1A2E, panels #FFF/#F5F6F8, red #EB2D37 only for Critical; Lato headings,
  Noto Sans body; layer colours water #2F6FE4, smooth #BFEFFF, rubble #FF9F1C,
  flood #FF5A36. 64_vendor_assets.py saves Leaflet, fonts and logo copies in
  web/vendor + web/assets (works offline). 65_export_explorer.py → web/data/
  explorer.js + x_*.png: own dark basemap GeoJSON (OSM roads, river/lake;
  blind-site OSM cached in data/raw/osm_blind_<site>.json); Hay River uses the
  judges'-page scenes and flood rules plus per-day predictions from watch.js;
  blind sites read the LOCKED image list/predictions only (stages: last pre-melt,
  max-rubble melt image before clearing, first ≥50% open water). Esri dark grey
  is an optional backup basemap in the layer menu.

- PITCH (5 min, 5 speakers, names TBD): 80_pitch_assets.py → outputs/pitch_assets/
  (charts + app screenshots + results.json with every quoted number + Lato/Noto Sans
  .ttf); 81_build_pitch.py → outputs/Polaris_Lifeline_Pitch.pptx (speaker notes) and
  outputs/Polaris_Lifeline_Script.md (649 words = 5:00 at 130 wpm, Q&A). Model is
  described honestly: radar RULES for ice + ridge regression on 46 springs (not ML on
  RCM images). Blind test shown as locked, NOT scored (placeholder). The 2021 "five
  NWT communities" source (gov.nt.ca) is deliberately unopened: it may reveal a
  blind-test outcome. 3,500 evacuated verified via Global News (May 16 2022).
  Slides 1-2 use Cabin Radio flood photos (outputs/pitch_assets/photos, copyright the
  photographers, credited; no freely licensed photos exist on Commons/NASA). Slide 3
  "watched today" example is sourced: GNWT Break-Up Report May 4 2026 (gauges, gauge
  photos, town camera, optical + RCM satellite images read by experts; no flood
  probability) and My North Now May 3 2026 (evacuation notice "after ... officials
  observe breakup activity within Hay River boundaries"). Keep web searches
  Hay River-only: blind-site 2026 ice notes appear in GNWT/CKLB breakup coverage.

## Existing work (keep — used for validation)
Earlier phase mapped flood extent around town; scripts 01–07 in `scripts/`:
- 02_preprocess.py: RCM zip → calibrated sigma0 dB (HH/HV), 5x5 speckle
  filter, GCP warp to EPSG:32611 10 m grid, cropped to the old town box
  (-115.95..-115.60, 60.715..60.92). Output data/processed/<window>/.
- 03_threshold_water.py, 05_train_model.py: threshold + random forest flood
  maps (data/processed/flood_maps/). Model is weak (F1 ~0.16 vs NRCan labels).
- 04_make_labels.py: NRCan EGS May 14 2022 flood polygons (Capella) + hand
  labels → label rasters. EGS credit line required in any presentation.
- 06_get_osm.py, 07_alerts.py: OSM buildings/roads and impact alerts.
RCM scenes in data/rcm/<window>/ were downloaded manually from EODMS (all
HH+HV GRD; mostly 16M beams; reference = 2021-04-17 16M17, frozen river).

## Environment
- Windows, PowerShell, Python 3.14 (venv in ./venv), packages in requirements.txt
- Run scripts as: `venv\Scripts\python.exe scripts\<name>.py`
- Scripts are numbered in pipeline order
- EODMS credentials in .env (never print or commit them)

## Working style
- I'm new to programming: explain what each step does in plain language,
  and say clearly when I need to do something myself (credentials,
  installing software, checking results).
- Build the simplest working version of each part first, then improve.
