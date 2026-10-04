"""
Step 1b (new plan): Search the EODMS archive for RCM scenes over the river
corridor for every spring since RCM launched (2020 onward).

Only SEARCHES the catalogue - nothing is ordered or downloaded.

For each scene found it works out how much of the river it actually covers
(km along the river, from the lake upstream), because a scene can touch the
search area but miss most of the river.

Outputs:
    outputs/rcm_corridor_scenes.csv   one row per scene
    printed summary: usable scenes per spring and per beam mode

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\11_search_rcm_corridor.py
"""

import ast
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from eodms_rapi import EODMSRAPI
from shapely.geometry import Point, shape

PROJECT_DIR = Path(__file__).resolve().parent.parent
CORRIDOR_FILE = PROJECT_DIR / "data" / "processed" / "corridor" / "corridor.gpkg"
OUT_CSV = PROJECT_DIR / "outputs" / "rcm_corridor_scenes.csv"

YEARS = range(2020, 2027)
SEASON = ("0315", "0615")        # mid-March (solid ice) to mid-June (ice gone)
RIVER_KM = 55                    # length of river we care about
MOUTH_KM = 15                    # the jam-prone reach: lake up past the town
MAP_CRS = "EPSG:32611"
MAX_RESULTS = 3000               # EODMS returns only 20 per search unless told otherwise


def km_covered(footprint_utm, centreline):
    """Which part of the river (km from lake) lies inside a scene footprint."""
    stations = np.arange(0, RIVER_KM * 1000 + 1, 250)
    inside = np.array([footprint_utm.contains(centreline.interpolate(s)) for s in stations])
    if not inside.any():
        return 0.0, None, None
    covered_km = inside.sum() * 0.25
    return covered_km, stations[inside].min() / 1000, stations[inside].max() / 1000


if __name__ == "__main__":
    load_dotenv(PROJECT_DIR / ".env")
    user, password = os.getenv("EODMS_USER"), os.getenv("EODMS_PASSWORD")
    if not user or not password:
        raise SystemExit("Please fill in EODMS_USER and EODMS_PASSWORD in .env")

    centreline = gpd.read_file(CORRIDOR_FILE, layer="centreline").geometry.iloc[0]
    corridor = gpd.read_file(CORRIDOR_FILE, layer="corridor")
    # A simplified outline is plenty for the search; exact coverage is checked after.
    search_area = corridor.to_crs("EPSG:4326").geometry.iloc[0].convex_hull.simplify(0.005)

    rapi = EODMSRAPI(user, password)
    rows = []
    for year in YEARS:
        print(f"\nSearching spring {year} ...")
        rapi.search("RCMImageProducts",
                    features=[("intersects", search_area.wkt)],
                    dates=[{"start": f"{year}{SEASON[0]}_000000", "end": f"{year}{SEASON[1]}_235959"}],
                    result_fields=["Beam Mnemonic", "Polarization", "Product Type"],
                    max_results=MAX_RESULTS)
        results = rapi.get_results("brief", show_progress=False) or []
        rapi.clear_results()
        if results and "errors" in results[0]:
            print("  EODMS error:", results[0]["errors"])
            continue
        print(f"  {len(results)} scenes touch the search area")
        for r in results:
            geom = r["geometry"]
            geom = ast.literal_eval(geom) if isinstance(geom, str) else geom
            fp = gpd.GeoSeries([shape(geom)], crs="EPSG:4326").to_crs(MAP_CRS).iloc[0]
            km, km_from, km_to = km_covered(fp, centreline)
            rows.append({
                "year": year,
                "date_utc": r["date"][:19],
                "title": r["title"],
                "record_id": r["recordId"],
                "product_type": r["type"],
                "beam": r["beamMnemonic"],
                "beam_description": r.get("beamModeDescription"),
                "polarization": r["polarization"],
                "pol_mode": r.get("polarizationDataMode"),
                "orbit": r.get("orbitDirection"),
                "resolution_m": r.get("spatialResolution"),
                "river_km_covered": km,
                "km_from": km_from,
                "km_to": km_to,
                "covers_mouth_reach": km_from is not None and km_from <= 1 and km_to >= MOUTH_KM,
                "orderable": r.get("isOrderable"),
            })

    table = pd.DataFrame(rows).sort_values("date_utc")
    already = {p.stem for p in (PROJECT_DIR / "data" / "rcm").glob("*/*.zip")}
    table["already_downloaded"] = table["title"].isin(already)
    OUT_CSV.parent.mkdir(exist_ok=True)
    table.to_csv(OUT_CSV, index=False)
    print(f"\nSaved {len(table)} scenes to {OUT_CSV}")

    # --- Summary -------------------------------------------------------------
    usable = table[(table["product_type"] == "GRD") & (table["river_km_covered"] > 0)]
    print("\nGRD scenes covering any of the river, by polarization:")
    print(usable.groupby(["polarization"]).size().to_string())
    dual = usable[usable["polarization"] == "HH HV"]
    print("\nHH+HV GRD scenes per spring (all / covering the lake-to-town reach / >=40 km of river):")
    summary = dual.groupby("year").agg(
        all=("title", "size"),
        mouth_reach=("covers_mouth_reach", "sum"),
        ge40km=("river_km_covered", lambda s: (s >= 40).sum()))
    print(summary.to_string())
    print("\nHH+HV GRD scenes by beam family:")
    print(dual.assign(family=dual["beam"].str.extract(r"^([A-Z]*\d*[A-Z]+)")[0])
          .groupby("family").size().sort_values(ascending=False).to_string())
