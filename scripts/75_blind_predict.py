"""
Blind test, step 6: make the blind predictions (RCM images + temperatures only).

Uses ONLY: preprocessed RCM scenes, the site's river-pixel map and jam zone,
and thawing degree-days from air temperatures. No gauge data, no flood
records, no outcomes. Rules are the ones locked in
outputs/blind_test/locked_rules_<UTC>.json (identical to Hay River's):

Per image
  * HH is set to "no data" where HV is missing (as script 31).
  * Viewing-angle correction: HH35 = HH + 0.18 * (angle - 35).
  * Classes: rubble/rough if HH35 >= -13 dB; below -20 dB = open water if melt
    has started (thawing degree-days since March 1 >= 20), else smooth ice;
    otherwise smooth ice.
  * Counts only if it sees at least 30% of the jam zone.
  * Jam-zone % rubble and % open water.
Per spring (site, year)
  * Melt-season images = taken on or after the day thaw reaches 20 TDD.
  * Ice cleared = first melt image with >= 50% open water in the jam zone;
    later images are not counted.
  * n_above = counted melt images with rubble >= 83.7%.
  * Level: Critical if n_above >= 2; Warning if n_above == 1; Watch if the
    highest rubble value is within 10 points below 83.7; otherwise Low.
    "Not enough images" if no melt image is counted.
  * Likelihood % = n_above / counted melt images (NOT a calibrated probability).
  * Confidence: starts High; one step lower for each flag: beam is not 16M;
    river > 3x wider than Hay River; tidal / sea-ice influence; fewer than 5
    counted melt images; no image before melt began.

Output: outputs/blind_test/predictions_<site-set>_<UTC>.csv (one row per spring)
        outputs/blind_test/prediction_images_<site-set>_<UTC>.csv (one row per image)
        and the file fingerprints appended to outputs/blind_test/lock_register.txt

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\75_blind_predict.py <site> [<site> ...]
    sites: hay_river (reference), fort_simpson, albany
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT = PROJECT_DIR / "outputs" / "blind_test"
PROC = PROJECT_DIR / "data" / "processed"

# --- Locked rules (identical to Hay River) ---
REF_ANGLE, ANGLE_SLOPE = 35.0, 0.18
RUBBLE_DB, DARK_DB = -13.0, -20.0
MELT_TDD = 20.0
MIN_JAM_COVERAGE = 0.30
RUBBLE_THRESHOLD = 83.7
WATCH_MARGIN = 10.0
CLEARED_WATER = 50.0
MIN_MELT_IMAGES = 5
YEARS = range(2021, 2027)

SITES = {
    "hay_river": {"label": "Hay River (reference)", "communities": "Hay River",
                  "flags": {"wide": False, "tidal": False}},
    "fort_simpson": {"label": "Mackenzie River at Fort Simpson", "communities": "Fort Simpson",
                     "flags": {"wide": True, "tidal": False}},
    "albany": {"label": "Albany River estuary", "communities": "Fort Albany and Kashechewan",
               "flags": {"wide": True, "tidal": True}},
}
SEPARATE = {("albany", 2025), ("albany", 2026)}      # 100 m only: low confidence, outside main scoring


def site_inputs(site):
    """Scene list, jam-zone mask and thaw series for a site."""
    if site == "hay_river":
        with rasterio.open(PROC / "corridor" / "river_pixels.tif") as src:
            km, channel = src.read(1), src.read(2)
        zone = np.isfinite(km) & (channel == 1) & (km <= 15)        # the training jam zone
        scenes = sorted((PROC / "corridor" / "scenes").glob("*.tif"))
        dd = pd.read_csv(PROC / "ice" / "daily_degree_days.csv", parse_dates=["date"])
        thaw = dd.set_index("date")["tdd"]
    else:
        with rasterio.open(PROC / "blind" / site / "river_pixels.tif") as src:
            zone = src.read(3) == 1
        scenes = sorted((PROC / "blind" / site / "scenes").glob("*.tif"))
        t = pd.read_csv(PROC / "blind" / site / "thaw.csv", parse_dates=["date"])
        thaw = t.set_index("date")["tdd"]
    scenes = [s for s in scenes if int(s.stem[:4]) in YEARS]
    return scenes, zone, thaw


def tdd_on(thaw, day):
    if day.month < 3:
        return 0.0
    v = thaw.get(day.normalize())
    return float(v) if v is not None and np.isfinite(v) else np.nan


def classify_image(path, zone, melt):
    with rasterio.open(path) as src:
        hh, hv, inc = src.read(1), src.read(2), src.read(3)
    hh = np.where(np.isfinite(hv), hh, np.nan)
    hh35 = hh + ANGLE_SLOPE * (inc - REF_ANGLE)
    seen = zone & np.isfinite(hh35)
    coverage = seen.sum() / max(zone.sum(), 1)
    v = hh35[seen]
    rubble = 100 * float((v >= RUBBLE_DB).mean()) if v.size else np.nan
    water = 100 * float((v < DARK_DB).mean()) if (v.size and melt) else 0.0
    return coverage, rubble, water


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == "__main__":
    sites = sys.argv[1:]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    img_rows, year_rows = [], []
    for site in sites:
        cfg = SITES[site]
        scenes, zone, thaw = site_inputs(site)
        print(f"\n===== {cfg['label']}: {len(scenes)} images, jam zone {zone.sum() * 100 / 1e6:.1f} km2")
        for path in scenes:
            when = pd.to_datetime(path.stem[:15], format="%Y%m%d_%H%M%S")
            beam = path.stem.split("_")[-1]
            tdd = tdd_on(thaw, when)
            melt = bool(np.isfinite(tdd) and tdd >= MELT_TDD)
            cov, rub, wat = classify_image(path, zone, melt)
            img_rows.append({"site": site, "year": when.year, "image": path.stem, "time_utc": when, "beam": beam,
                             "tdd": round(tdd, 1) if np.isfinite(tdd) else None, "melt_started": melt,
                             "jam_zone_coverage": round(cov, 2), "rubble_pct": None if np.isnan(rub) else round(rub, 1),
                             "open_water_pct": round(wat, 1), "counts": bool(cov >= MIN_JAM_COVERAGE)})
        imgs = pd.DataFrame([r for r in img_rows if r["site"] == site])
        for year in YEARS:
            y = imgs[(imgs["year"] == year) & imgs["counts"]].sort_values("time_utc")
            melt = y[y["melt_started"]]
            cleared = melt[melt["open_water_pct"] >= CLEARED_WATER]
            counted = melt if cleared.empty else melt[melt["time_utc"] < cleared["time_utc"].iloc[0]]
            pre_melt = (~y["melt_started"]).any()
            beams = sorted(set(y["beam"]))
            flags = []
            if any(not b.startswith("16M") for b in beams):
                flags.append("different beam/resolution from training (not 16M)")
            if cfg["flags"]["wide"]:
                flags.append("river much wider than Hay River")
            if cfg["flags"]["tidal"]:
                flags.append("tidal estuary / sea ice near the mouth")
            if len(counted) < MIN_MELT_IMAGES:
                flags.append(f"only {len(counted)} melt-season images before the ice cleared")
            if not pre_melt:
                flags.append("no image from before melt began")
            conf_steps = 3 - len(flags)
            confidence = {3: "High", 2: "Medium", 1: "Low"}.get(conf_steps, "Very low")
            if counted.empty:
                level, likelihood, n_above, top = "Not enough images", None, 0, None
                sentence = (f"No usable melt-season image of the river near {cfg['communities']} before the ice "
                            "cleared, so no prediction.")
            else:
                n_above = int((counted["rubble_pct"] >= RUBBLE_THRESHOLD).sum())
                top = counted.loc[counted["rubble_pct"].idxmax()]
                likelihood = round(100 * n_above / len(counted))
                if n_above >= 2:
                    level = "Critical"
                elif n_above == 1:
                    level = "Warning"
                elif top["rubble_pct"] >= RUBBLE_THRESHOLD - WATCH_MARGIN:
                    level = "Watch"
                else:
                    level = "Low"
                if n_above:
                    sentence = (f"{n_above} of {len(counted)} melt-season images show rubble ice covering at least "
                                f"{RUBBLE_THRESHOLD}% of the river near {cfg['communities']} "
                                f"(highest {top['rubble_pct']:.0f}% on {top['time_utc']:%b %d}).")
                else:
                    sentence = (f"No melt-season image shows rubble ice building up near {cfg['communities']}: "
                                f"the highest was {top['rubble_pct']:.0f}% on {top['time_utc']:%b %d}"
                                + (f", and the river was mostly open water by {cleared['time_utc'].iloc[0]:%b %d}."
                                   if not cleared.empty else "."))
            year_rows.append({
                "site": site, "site_label": cfg["label"], "year": year,
                "main_scoring": (site, year) not in SEPARATE and site != "hay_river",
                "risk_level": level, "flood_likelihood_pct": likelihood, "confidence": confidence,
                "explanation": sentence, "melt_images_counted": len(counted), "images_above_threshold": n_above,
                "max_rubble_pct": None if top is None else round(float(top["rubble_pct"]), 1),
                "ice_cleared_on": None if cleared.empty else f"{cleared['time_utc'].iloc[0]:%Y-%m-%d}",
                "beams": " ".join(beams), "confidence_flags": "; ".join(flags) or "none",
            })
            r = year_rows[-1]
            print(f"  {year}: {r['risk_level']:17s} likelihood {r['flood_likelihood_pct']}%  confidence "
                  f"{r['confidence']:8s} | {r['explanation']}")

    tag = "_".join(sites)
    pred = OUT / f"predictions_{tag}_{stamp}.csv"
    det = OUT / f"prediction_images_{tag}_{stamp}.csv"
    pd.DataFrame(year_rows).to_csv(pred, index=False)
    pd.DataFrame(img_rows).to_csv(det, index=False)
    with open(OUT / "lock_register.txt", "a", encoding="utf-8") as reg:
        for f in (pred, det):
            reg.write(f"{stamp}  {f.name}  sha256={sha256(f)}\n")
    print(f"\nLocked: {pred.name}\n  sha256 {sha256(pred)}\n        {det.name}\n  sha256 {sha256(det)}")
