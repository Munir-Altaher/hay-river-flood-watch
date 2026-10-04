"""
Blind test, step 5: LOCK the method before any prediction is made.

Writes outputs/blind_test/locked_rules_<UTC>.json with:
  * the jam-zone rule and each site's zone (from step 71),
  * every classification threshold and the yearly scoring (identical to Hay River),
  * image choices, weather stations, confidence rules,
  * SHA-256 fingerprints of the prediction code (75_blind_predict.py), each
    site's river-pixel map and thaw file - so any later change is detectable.
The fingerprint of the lock file itself is added to lock_register.txt.

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\74_blind_lock_rules.py
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT = PROJECT_DIR / "outputs" / "blind_test"
PROC = PROJECT_DIR / "data" / "processed"


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


if __name__ == "__main__":
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sites = {}
    for site in ["fort_simpson", "albany"]:
        info = json.loads((PROC / "blind" / site / "site_info.json").read_text())
        thaw = pd.read_csv(PROC / "blind" / site / "thaw.csv")
        sites[site] = {
            "jam_zone": info,
            "weather_station": thaw["station"].iloc[0],
            "river_pixels_sha256": sha256(PROC / "blind" / site / "river_pixels.tif"),
            "thaw_csv_sha256": sha256(PROC / "blind" / site / "thaw.csv"),
        }
    rules = {
        "locked_utc": stamp,
        "purpose": "Blind test of the Hay River RCM ice rule at two new sites. No retraining, no outcome data.",
        "jam_zone_rule": ("Every connected channel of every river flowing past the community, from 5 km downstream "
                          "of the community (or the river mouth if closer) to 5 km upstream of it; community extent "
                          "= 5th to 95th percentile of OpenStreetMap buildings measured along the river. Gives "
                          "km 0 to 15.4 at Hay River (training zone km 0 to 15). River geometry only."),
        "sites": sites,
        "hay_river_reference": {"jam_zone": "main/East Channel, km 0 to 15 above Great Slave Lake (training zone)",
                                "images": "16M, 2021-2026", "weather": "Hay River A (merged stations)"},
        "images": {"hay_river": "16M HH+HV GRD", "fort_simpson": "16M HH+HV GRD (same as training)",
                   "albany_2021_2024": "SC30M (30 m ScanSAR) HH+HV GRD: cross-resolution test",
                   "albany_2025_2026": "SCLN (100 m ScanSAR) HH+HV GRD: reported separately, low confidence, "
                                       "outside main scoring"},
        "preprocessing": "rcm_utils.read_scene: sigma0 from lutSigma, 5x5 speckle window, GCP thin-plate warp to "
                         "10 m local UTM grid (identical to Hay River)",
        "classification": {"angle_correction": "HH35 = HH + 0.18 * (incidence - 35)",
                           "rubble_rough_ice": "HH35 >= -13 dB", "open_water": "HH35 < -20 dB once melt has started",
                           "smooth_ice": "everything else", "hh_masked_where_hv_missing": True},
        "melt_rule": "thawing degree-days since March 1 >= 20 (daily mean air temperature above 0 C)",
        "image_counts_if": "it sees at least 30% of the jam zone",
        "ice_cleared": "first melt-season image with >= 50% open water in the jam zone; later images not counted",
        "yearly_scoring": {"Critical": ">= 2 counted melt images with jam-zone rubble >= 83.7%",
                           "Warning": "exactly 1 such image",
                           "Watch": "highest jam-zone rubble between 73.7% and 83.7%",
                           "Low": "otherwise",
                           "Not enough images": "no counted melt image"},
        "rubble_threshold_pct": 83.7,
        "threshold_origin": "halfway between Hay River 2022 (flood) and 2023 (no flood); see script 41",
        "flood_likelihood_pct": "share of counted melt images at or above 83.7% (NOT a calibrated probability)",
        "confidence": {"start": "High", "one_step_lower_for_each": [
            "beam not 16M", "river more than 3x wider than Hay River", "tidal / sea-ice influence",
            "fewer than 5 counted melt images", "no image before melt began"],
            "steps": "High, Medium, Low, Very low"},
        "code_sha256": {"75_blind_predict.py": sha256(PROJECT_DIR / "scripts" / "75_blind_predict.py"),
                        "rcm_utils.py": sha256(PROJECT_DIR / "scripts" / "rcm_utils.py"),
                        "73_blind_preprocess.py": sha256(PROJECT_DIR / "scripts" / "73_blind_preprocess.py")},
    }
    path = OUT / f"locked_rules_{stamp}.json"
    path.write_text(json.dumps(rules, indent=1), encoding="utf-8")
    with open(OUT / "lock_register.txt", "a", encoding="utf-8") as reg:
        reg.write(f"{stamp}  {path.name}  sha256={sha256(path)}\n")
    print(f"Locked rules: {path.name}\n  sha256 {sha256(path)}")
