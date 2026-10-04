"""
Blind test, step 7: export the LOCKED blind-test predictions for the website.

Reads the locked prediction files (never changes them), checks each file's
SHA-256 fingerprint against outputs/blind_test/lock_register.txt, and writes
web/data/blind.js for the demo (blind-test section) and the user view.

Outcomes are NOT looked up: the two new sites show "Not checked yet". Hay River
(the training site) shows its documented outcome from the GNWT flood history
already in the project (data/processed/risk/breakup_history.csv).

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\76_export_blind_web.py
"""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
BT = PROJECT_DIR / "outputs" / "blind_test"
DATA = PROJECT_DIR / "web" / "data"


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


if __name__ == "__main__":
    register = {}
    for line in (BT / "lock_register.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\S+)\s+(\S+)\s+sha256=(\w+)", line)
        if m:
            register[m.group(2)] = {"utc": m.group(1), "sha256": m.group(3)}

    # Latest locked file per site set.
    preds, images, locks = [], [], []
    for tag in ["hay_river_fort_simpson", "albany"]:
        p = sorted(BT.glob(f"predictions_{tag}_*.csv"))[-1]
        d = sorted(BT.glob(f"prediction_images_{tag}_*.csv"))[-1]
        for f in (p, d):
            ok = register.get(f.name, {}).get("sha256") == sha256(f)
            if not ok:
                raise SystemExit(f"{f.name}: fingerprint does not match the lock register - not exporting")
        preds.append(pd.read_csv(p))
        images.append(pd.read_csv(d, parse_dates=["time_utc"]))
        locks.append({"file": p.name, "utc": register[p.name]["utc"], "sha256": register[p.name]["sha256"]})
    rules_file = sorted(BT.glob("locked_rules_*.json"))[-1]
    rules = json.loads(rules_file.read_text(encoding="utf-8"))
    pred = pd.concat(preds)
    img = pd.concat(images)

    hist = pd.read_csv(PROJECT_DIR / "data" / "processed" / "risk" / "breakup_history.csv", index_col="year")
    hay_outcome = {y: ("Flood (documented)" if bool(hist.loc[y, "documented_flood"]) else "No documented flood")
                   if y in hist.index else "No documented flood" for y in range(2021, 2027)}

    sites = {}
    meta = {
        "hay_river": {"name": "Hay River", "where": "Hay River, NT", "role": "Training site",
                      "images": "16 m (16M), same as training", "station": "Hay River A", "lat": 60.82, "lon": -115.79},
        "fort_simpson": {"name": "Fort Simpson", "where": "Mackenzie and Liard rivers, NT", "role": "Blind test",
                         "images": "16 m (16M), same as training",
                         "station": rules["sites"]["fort_simpson"]["weather_station"], "lat": 61.8631, "lon": -121.3543},
        "albany": {"name": "Albany River", "where": "Fort Albany and Kashechewan, ON", "role": "Blind test",
                   "images": "30 m ScanSAR (2021 to 2024), 100 m (2025, 2026): cross-resolution test",
                   "station": rules["sites"]["albany"]["weather_station"], "lat": 52.25, "lon": -81.66},
    }
    for site, g in pred.groupby("site"):
        rows = []
        for _, r in g.sort_values("year").iterrows():
            yi = img[(img["site"] == site) & (img["year"] == r["year"]) & img["counts"]].sort_values("time_utc")
            rows.append({
                "year": int(r["year"]), "level": r["risk_level"],
                "likelihood": None if pd.isna(r["flood_likelihood_pct"]) else int(r["flood_likelihood_pct"]),
                "confidence": r["confidence"], "why": r["explanation"], "flags": r["confidence_flags"],
                "main": bool(r["main_scoring"]), "beams": r["beams"],
                "outcome": hay_outcome[int(r["year"])] if site == "hay_river" else "Not checked yet",
                "images": [[t.strftime("%m-%d"), None if pd.isna(rb) else round(float(rb)), bool(m),
                            round(float(w))] for t, rb, m, w in
                           zip(yi["time_utc"], yi["rubble_pct"], yi["melt_started"], yi["open_water_pct"])],
                "cleared": None if pd.isna(r["ice_cleared_on"]) else str(r["ice_cleared_on"])[5:],
            })
        sites[site] = {**meta[site], "years": rows}
    out = {"sites": sites, "locks": locks,
           "rules": {"file": rules_file.name, "utc": rules["locked_utc"], "sha256": register[rules_file.name]["sha256"],
                     "threshold": rules["rubble_threshold_pct"]}}
    (DATA / "blind.js").write_text("window.HRFW = window.HRFW || {};\nwindow.HRFW.blind = "
                                   + json.dumps(out, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("Fingerprints verified. Saved web/data/blind.js")
    for s, v in sites.items():
        print(f"  {v['name']}: " + ", ".join(f"{r['year']} {r['level']}" for r in v["years"]))
