"""
Step 5 (new plan): Turn a forecast water level into a projected flood map.

Method (HAND - "height above nearest drainage", with a sloping water surface)
----------------------------------------------------------------------------
1. Normal river surface: from the 2020 lidar ground model (5 m pixels, metres
   above sea level, CGVD2013), the height of the river's water surface on a
   normal day, at each km along the river (km 0 = Great Slave Lake).
2. HAND: for every land pixel, find the nearest river pixel; HAND = ground
   height minus the normal river surface there. Low HAND = barely above the
   river.
3. Flood water surface during an ice jam is NOT flat: it slopes down from
   the gauge to the lake. We draw a straight line from the forecast level at
   the gauge (07OB001, km GAUGE_KM) down to the level at the river mouth. In
   2022 this was 170.8 m at the gauge and 158.2 m at the mouth (GNWT 2025).
   Upstream of the gauge the water is assumed to stand the same depth above
   normal as at the gauge.
4. A pixel floods if its HAND is less than the flood depth at its nearest
   river point (flood surface minus normal surface), AND it is connected to
   the river through other flooded pixels (low ground behind a ridge stays
   dry).

Datums: GNWT gauge levels are Geodetic Survey of Canada (~CGVD28); the lidar is
CGVD2013. The report's conversion for this gauge is -0.12 m (CGVD28 -> 2013).

Limitations: a straight-line water surface is a simplification of the real
ice-jam profile; dykes, culverts and road embankments smaller than 5 m are
not represented; only areas covered by the 2020 lidar are mapped.

Outputs
-------
data/processed/flood_projection/hand_5m.tif, river_km_nearest_5m.tif, normal_surface_by_km.csv
data/processed/flood_projection/flood_<level>.tif           projected extent per scenario
data/processed/flood_projection/impact_curve.csv            buildings/roads vs gauge level
data/processed/flood_projection/validation_2022.csv
outputs/flood_projection/*.png

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\50_flood_projection.py
"""

from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.features import geometry_mask, rasterize
from rasterio.warp import reproject, Resampling
from scipy.ndimage import binary_dilation, distance_transform_edt, label

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEM = PROJECT_DIR / "data" / "raw" / "dem" / "dem_town_5m.tif"
CORRIDOR = PROJECT_DIR / "data" / "processed" / "corridor" / "corridor.gpkg"
OSM = PROJECT_DIR / "data" / "raw" / "osm_hay_river.gpkg"
RCM_FLOOD_2022 = PROJECT_DIR / "data" / "processed" / "flood_maps" / "20220512_011316_16M7_flood.tif"
EGS_FLOOD = (PROJECT_DIR / "data" / "labels" / "Flood_CAN_NT_Hay_20220514_182929" /
             "Flood_CAN_NT_Hay_20220514_182929.shp")
EGS_FOOTPRINT = EGS_FLOOD.with_name("Footprint_CAN_NT_Hay_20220514_182929.shp")
OUT = PROJECT_DIR / "data" / "processed" / "flood_projection"
FIGS = PROJECT_DIR / "outputs" / "flood_projection"

GAUGE_LONLAT = (-115.860, 60.743)     # WSC 07OB001
CGVD28_TO_2013 = -0.12                # GNWT (2025), for the 07OB001 gauge
MOUTH_2022 = 158.18                   # 2022 peak water level at the mouth, CGVD2013 (GNWT Table 22)
MOUTH_TYPICAL = 157.0                 # typical breakup level at the mouth for the impact curve
MOUTH_LEVELS = [MOUTH_TYPICAL, 158.18]  # impact curves for a typical lake and a high lake (2022)
GAUGE_2022 = 170.90                   # 2022 instantaneous peak at the gauge (GNWT Table 16)
LAKE_LIDAR_M = 157.0                  # Great Slave Lake when the lidar was flown (July 2020: 156.91 m)
# Shape of the ice-jam water surface between the mouth and the gauge:
#   surface = mouth + (gauge - mouth) * (km / gauge_km) ** PROFILE_EXPONENT
# 1.0 = straight line. Below 1 the surface rises faster near the mouth, as
# real jam profiles do. 0.6 was chosen from the 2022 event (so 2022 is not an
# independent test of it):
#   * a straight line (1.0) leaves Vale Island dry and floods ~50 buildings,
#     but ~500 homes and 70 businesses were damaged in 2022 (CBC/GNWT);
#   * 0.6 floods ~625 OpenStreetMap buildings (OSM also maps sheds/garages)
#     and covers most of the flooding seen in the RCM and NRCan 2022 maps.
# Overlap scores (IoU) alone would pick 1.0 only because both reference maps
# are small (NRCan's is from May 14, after the water dropped).
PROFILE_EXPONENT = 0.6
CALIBRATION_EXPONENTS = [1.0, 0.8, 0.6, 0.5, 0.4, 0.3]
NORMAL_PERCENTILE = 30                # river-surface height = 30th percentile of river pixels per km
SCENARIO_LEVELS = np.round(np.arange(164.0, 172.01, 0.25), 2)
MAP_LEVELS = [166.4, 167.75, 170.9]   # Watch threshold, Warning threshold, 2022 peak
TOWN_BOX = (-115.84, 60.74, -115.70, 60.88)

INK, MUTED, AXIS, GRID = "#0b0b0b", "#898781", "#c3c2b7", "#e1e0d9"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"


def prepare():
    """Normal river surface, HAND and nearest-river km on the 5 m DEM grid (cached)."""
    with rasterio.open(DEM) as src:
        dem = src.read(1)
        profile = src.profile
        transform, crs = src.transform, src.crs
    river = gpd.read_file(CORRIDOR, layer="river_mask").union_all()
    centre = gpd.read_file(CORRIDOR, layer="centreline").geometry.iloc[0]
    in_river_outline = ~geometry_mask([river], dem.shape, transform) & np.isfinite(dem)

    # Great Slave Lake: the biggest connected area at or below the lake level
    # of the lidar survey. It is permanent water, not land that can flood.
    low, _ = label(np.isfinite(dem) & (dem <= LAKE_LIDAR_M), structure=np.ones((3, 3)))
    sizes = np.bincount(low.ravel())
    sizes[0] = 0
    lake = low == np.argmax(sizes)
    print(f"Great Slave Lake in the lidar area: {lake.sum() * 25 / 1e6:.1f} km2 (treated as permanent water)")

    rows, cols = np.nonzero(in_river_outline)
    xs, ys = rasterio.transform.xy(transform, rows, cols)
    km_river = shapely.line_locate_point(centre, shapely.points(np.array(xs), np.array(ys))) / 1000
    surface = pd.DataFrame({"km": np.floor(km_river).astype(int), "z": dem[rows, cols]})
    normal = surface.groupby("km")["z"].quantile(NORMAL_PERCENTILE / 100)
    # The river can't flow uphill: make the surface rise (or stay) going upstream.
    normal = normal.sort_index().cummax()
    normal_at = np.interp(km_river, normal.index + 0.5, normal.to_numpy())

    # Nearest permanent water (river or lake) for every pixel; the lake counts as km 0.
    is_river = in_river_outline | lake
    _, (ir, ic) = distance_transform_edt(~is_river, return_indices=True)
    river_surface = np.full(dem.shape, np.nan, dtype=np.float32)
    river_km = np.full(dem.shape, np.nan, dtype=np.float32)
    river_surface[lake] = normal.iloc[0]
    river_km[lake] = 0.0
    river_surface[rows, cols] = normal_at
    river_km[rows, cols] = km_river
    nearest_surface = river_surface[ir, ic]
    nearest_km = river_km[ir, ic]
    hand = (dem - nearest_surface).astype(np.float32)

    gauge = gpd.GeoSeries(gpd.points_from_xy([GAUGE_LONLAT[0]], [GAUGE_LONLAT[1]]), crs=4326).to_crs(crs).iloc[0]
    gauge_km = centre.project(gauge) / 1000
    return dict(dem=dem, hand=hand, nearest_km=nearest_km, is_river=is_river, normal=normal,
                gauge_km=gauge_km, transform=transform, crs=crs, profile=profile)


def flood_extent(p, gauge_level_cgvd28, mouth_level, exponent=None):
    """Boolean flood map for a gauge level (report datum) and a mouth level (CGVD2013)."""
    exponent = PROFILE_EXPONENT if exponent is None else exponent
    gauge_level = gauge_level_cgvd28 + CGVD28_TO_2013
    normal = p["normal"]
    normal_gauge = float(np.interp(p["gauge_km"], normal.index + 0.5, normal.to_numpy()))
    km = p["nearest_km"]
    normal_here = np.interp(km, normal.index + 0.5, normal.to_numpy())
    below = np.clip(km / p["gauge_km"], 0, 1) ** exponent
    surface = np.where(km <= p["gauge_km"],
                       mouth_level + (gauge_level - mouth_level) * below,
                       normal_here + (gauge_level - normal_gauge))
    depth_needed = surface - normal_here               # flood depth above normal at that river point
    wet = np.isfinite(p["hand"]) & (p["hand"] < depth_needed) & ~p["is_river"]
    # Keep only wet areas that connect to the river.
    seeds = binary_dilation(p["is_river"], iterations=2)
    labels, _ = label(wet | p["is_river"], structure=np.ones((3, 3)))
    keep = np.unique(labels[seeds & (labels > 0)])
    connected = np.isin(labels, keep) & wet
    return connected, surface


def burn(gdf, shape, transform):
    if gdf.empty:
        return np.zeros(shape, bool)
    return rasterize(((g, 1) for g in gdf.geometry), out_shape=shape, transform=transform,
                     fill=0, dtype="uint8", all_touched=True).astype(bool)


def impacts(flooded, transform, buildings, roads):
    shape = flooded.shape
    hit = []
    for geom in buildings.geometry:
        r = rasterize([(geom, 1)], out_shape=shape, transform=transform, all_touched=True)
        hit.append(bool((flooded & (r == 1)).any()))
    return np.array(hit)


def style(ax):
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    p = prepare()
    shape, transform, crs = p["dem"].shape, p["transform"], p["crs"]
    prof = p["profile"].copy()
    prof.update(dtype="float32", nodata=np.nan, compress="deflate")
    with rasterio.open(OUT / "hand_5m.tif", "w", **prof) as dst:
        dst.write(p["hand"], 1)
    p["normal"].rename("normal_surface_m").to_csv(OUT / "normal_surface_by_km.csv")
    print(f"Gauge 07OB001 is {p['gauge_km']:.1f} km up the river from the lake")
    print("Normal river surface (CGVD2013) at km 0/5/10/15/20:",
          [round(float(np.interp(k, p['normal'].index + 0.5, p['normal'].to_numpy())), 2) for k in (0, 5, 10, 15, 20)])

    # --- Buildings and roads, pre-burned for fast counting --------------------
    buildings = gpd.read_file(OSM, layer="buildings").to_crs(crs).reset_index(drop=True)
    roads = gpd.read_file(OSM, layer="roads").to_crs(crs)
    places = gpd.read_file(OSM, layer="places").to_crs(crs)
    places = places[(places["place"] != "town") & ~places["name"].str.fullmatch(r"Island [A-Z]")]
    near = gpd.sjoin_nearest(buildings[["geometry"]], places[["name", "geometry"]], how="left",
                             max_distance=1500)
    buildings["area"] = near[~near.index.duplicated()]["name"].fillna("other areas")
    ids = rasterize(((g, i + 1) for i, g in enumerate(buildings.geometry)), out_shape=shape,
                    transform=transform, fill=0, all_touched=True, dtype="int32")
    on_lidar = np.bincount(ids[np.isfinite(p["dem"])], minlength=len(buildings) + 1)[1:] > 0
    road_px = rasterize(((g.buffer(3), 1) for g in roads.geometry), out_shape=shape,
                        transform=transform, fill=0, dtype="uint8").astype(bool)

    def count(flooded):
        hit = np.bincount(ids[flooded], minlength=len(buildings) + 1)[1:] > 0
        return hit

    # --- 2022 validation and choice of the water-surface shape -----------------------
    # (a) Our RCM-derived flood map (May 11 evening scene), resampled to 5 m.
    rcm = np.full(shape, 255, dtype=np.uint8)
    with rasterio.open(RCM_FLOOD_2022) as src:
        reproject(rasterio.band(src, 1), rcm, dst_transform=transform, dst_crs=crs,
                  resampling=Resampling.nearest, src_nodata=255, dst_nodata=255)
    # (b) NRCan EGS May 14 flood polygons (class 2) inside the Capella footprint.
    egs = gpd.read_file(EGS_FLOOD).to_crs(crs)
    egs_flood = burn(egs[egs["class"] == 2], shape, transform)
    egs_foot = burn(gpd.read_file(EGS_FOOTPRINT).to_crs(crs), shape, transform)
    lidar = np.isfinite(p["dem"]) & ~p["is_river"]
    references = [
        ("RCM flood map, May 11 19:13 (this project)", rcm == 1, lidar & (rcm != 255) & (rcm != 2)),
        ("NRCan EGS flood polygons, May 14 (Capella)", egs_flood, lidar & egs_foot),
    ]
    val = []
    for exponent in CALIBRATION_EXPONENTS:
        flood22, _ = flood_extent(p, GAUGE_2022, MOUTH_2022, exponent)
        hit22 = count(flood22)
        for name, observed, valid in references:
            o, pr = observed & valid, flood22 & valid
            tp, fp, fn = (o & pr).sum(), (~o & pr).sum(), (o & ~pr).sum()
            val.append({"profile_exponent": exponent, "compared_with": name,
                        "buildings_in_projection": int(hit22.sum()),
                        "observed_flood_km2": round(o.sum() * 25 / 1e6, 2),
                        "projected_flood_km2": round(pr.sum() * 25 / 1e6, 2),
                        "share_of_observed_inside_projection": round(tp / max(tp + fn, 1), 2),
                        "share_of_projection_observed": round(tp / max(tp + fp, 1), 2),
                        "IoU": round(tp / max(tp + fp + fn, 1), 3)})
    val = pd.DataFrame(val)
    val.to_csv(OUT / "validation_2022.csv", index=False)
    print("\n2022 peak scenario (gauge 170.9 m, mouth 158.18 m) compared with the 2022 flood maps:")
    print(val.drop(columns=["observed_flood_km2"]).to_string(index=False))
    print(f"Water-surface shape used from here on: exponent {PROFILE_EXPONENT} "
          "(matches the ~570 homes/businesses damaged in 2022; see note at the top)")
    flood22, _ = flood_extent(p, GAUGE_2022, MOUTH_2022)

    # --- Impact curve -----------------------------------------------------------
    rows = []
    for mouth, level in [(m, l) for m in MOUTH_LEVELS for l in SCENARIO_LEVELS]:
        flooded, _ = flood_extent(p, level, mouth)
        hit = count(flooded)
        by_area = buildings.loc[hit, "area"].value_counts().to_dict()
        rows.append({"mouth_level_m": mouth, "gauge_level_m": level,
                     "flooded_km2": round(flooded.sum() * 25 / 1e6, 2),
                     "buildings_flooded": int(hit.sum()),
                     "road_km_flooded": round((flooded & road_px).sum() * 5 / 1000 / 1.2, 1),
                     **{f"bldg_{k.replace(' ', '_')}": v for k, v in by_area.items()}})
        if level in MAP_LEVELS:
            out_prof = p["profile"].copy()
            out_prof.update(dtype="uint8", nodata=255, compress="deflate")
            with rasterio.open(OUT / f"flood_{level:.2f}_mouth{mouth:.2f}.tif", "w", **out_prof) as dst:
                dst.write(np.where(np.isfinite(p["dem"]), flooded, 255).astype("uint8"), 1)
    curve = pd.DataFrame(rows).fillna(0)
    curve.to_csv(OUT / "impact_curve.csv", index=False)
    print(f"\nImpact curve ({on_lidar.sum()} of {len(buildings)} buildings are inside the lidar area):")
    wide = curve[curve["gauge_level_m"].isin(SCENARIO_LEVELS[::4])].pivot(
        index="gauge_level_m", columns="mouth_level_m", values="buildings_flooded")
    wide.columns = [f"buildings, mouth {c} m" for c in wide.columns]
    print(wide.to_string())


    # --- Pictures ------------------------------------------------------------------
    from rasterio.warp import transform as tf
    xs, ys = tf("EPSG:4326", crs, TOWN_BOX[::2], TOWN_BOX[1::2])
    ext = [transform.c, transform.c + transform.a * shape[1], transform.f + transform.e * shape[0], transform.f]
    hill = p["dem"]

    fig, axes = plt.subplots(1, 3, figsize=(20, 9))
    for ax, level in zip(axes, MAP_LEVELS):
        flooded, _ = flood_extent(p, level, MOUTH_2022 if level == GAUGE_2022 else MOUTH_TYPICAL)
        ax.imshow(hill, extent=ext, cmap="Greys_r", vmin=155, vmax=175)
        ax.imshow(np.where(p["is_river"], 1.0, np.nan), extent=ext, cmap=ListedColormap([BLUE]))
        ax.imshow(np.where(flooded, 1.0, np.nan), extent=ext, cmap=ListedColormap([ORANGE]), alpha=0.75)
        buildings.plot(ax=ax, color=INK, linewidth=0, markersize=0.5)
        ax.set_xlim(xs[0], xs[1]); ax.set_ylim(ys[0], ys[1])
        ax.set_xticks([]); ax.set_yticks([])
        n = count(flooded).sum()
        label_txt = {166.4: "Watch threshold", 167.75: "Warning threshold", 170.9: "2022 peak"}[level]
        ax.set_title(f"Gauge at {level:.2f} m ({label_txt}): {n} buildings", loc="left", color=INK)
    fig.suptitle("Projected flooding (orange) for three water levels at the town gauge", color=INK)
    plt.tight_layout(); plt.savefig(FIGS / "projected_flood_levels.png", dpi=70); plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(15, 9))
    for ax, (name, observed) in zip(axes, [("RCM flood map, May 11 19:13 (this project)", rcm == 1),
                                           ("NRCan EGS flood polygons, May 14", egs_flood)]):
        ax.imshow(hill, extent=ext, cmap="Greys_r", vmin=155, vmax=175)
        ax.imshow(np.where(flood22 & ~observed, 1.0, np.nan), extent=ext, cmap=ListedColormap([ORANGE]), alpha=0.6)
        ax.imshow(np.where(observed & lidar, 1.0, np.nan), extent=ext, cmap=ListedColormap([BLUE]), alpha=0.9)
        ax.imshow(np.where(flood22 & observed, 1.0, np.nan), extent=ext, cmap=ListedColormap([AQUA]))
        ax.set_xlim(xs[0], xs[1]); ax.set_ylim(ys[0], ys[1])
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"2022 projection vs {name}\naqua = both, orange = projection only, blue = observed only",
                     loc="left", color=INK, fontsize=10)
    plt.tight_layout(); plt.savefig(FIGS / "validation_2022.png", dpi=70); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    for mouth, colour in zip(MOUTH_LEVELS, [BLUE, ORANGE]):
        c = curve[curve["mouth_level_m"] == mouth]
        ax.plot(c["gauge_level_m"], c["buildings_flooded"], color=colour, linewidth=2,
                label=f"level at river mouth {mouth} m" + (" (2022)" if mouth == MOUTH_2022 else " (typical)"))
    ax.legend(frameon=False, loc="upper left")
    for y, name in [(166.4, "Watch"), (167.75, "Warning"), (170.9, "2022 peak")]:
        ax.axvline(y, color=AXIS, linewidth=1)
        ax.annotate(name, (y, ax.get_ylim()[1] * 0.95), xytext=(3, 0), textcoords="offset points",
                    fontsize=9, color=MUTED)
    ax.set_xlabel("peak water level at the town gauge 07OB001 (m above sea level)", color=MUTED)
    ax.set_ylabel("buildings in projected flood area", color=MUTED)
    ax.set_title("Projected buildings flooded vs peak level at the town gauge",
                 loc="left", color=INK, fontsize=11)
    style(ax)
    plt.tight_layout(); plt.savefig(FIGS / "impact_curve.png", dpi=110); plt.close(fig)
    print(f"\nOutputs in {OUT} and {FIGS}")
