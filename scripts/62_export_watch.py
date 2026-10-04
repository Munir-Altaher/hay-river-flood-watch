"""
Step 8 (user view): Export data for "Breakup Watch Canada" (web/watch.html), a
weather-app style early-warning page with a time machine: pick any day and see
what the system would have said that day, using only data available then.

For Hay River, for every day from January 1 to June 30 of each year 1976-2026:
  * risk level and confidence ("chance the spring peak reaches flood level"),
    from the risk model (script 41). Years up to 2024 are predicted by a model
    that never saw that year; 2025-2026 by the final model (never saw them either).
    Before April 1 this is labelled an early outlook.
  * RCM evidence (2021 onward): the latest image within the last days, with the
    same jam-zone rule as script 41.
  * "When": the breakup danger window - when the ice is most likely to break up
    and jam (the time a flood would happen). Breakup at Hay River comes after
    49-87 thawing degree-days (step 2). Starting from the warmth built up so far,
    every OTHER past spring's weather is replayed forward from that day; the
    days on which the total reaches 49/59/87 give the window (25-75%).
  * breakup over: once enough warmth has passed (TDD >= OVER_TDD), RCM shows the
    jam zone mostly open water, or the river has dropped well below its spring high.

Other sites on the Canada map are SIMULATED in the web page itself (clearly
labelled); only Hay River uses real data.

Outputs: web/data/watch.js, web/data/img/w_ice_<scene>.png, w_flood_<level>_<mouth>.png

Run from the project folder (takes a few minutes):
    venv\\Scripts\\python.exe scripts\\62_export_watch.py
"""

import importlib.util
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import rasterio

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROC = PROJECT_DIR / "data" / "processed"
RAW = PROJECT_DIR / "data" / "raw"
DATA = PROJECT_DIR / "web" / "data"
IMG = DATA / "img"
MERGED = PROC / "gauges_merged"

# The user view starts when RCM images are available in this project (spring 2021).
FIRST_YEAR, LAST_DAY = 2021, pd.Timestamp("2026-10-03")
EARLY_OUTLOOK_BEFORE = "04-01"
TDD_AT_PEAK = [49, 59, 87]          # quartiles of thaw at the town-gauge peak, 2002-2024 (step 2)
OVER_TDD = 150                      # this much thaw: breakup is over
DROP_M, RISE_M = 1.5, 2.0           # river fell this far from a spring high that rose this much: over
RCM_LOOKBACK_DAYS = 10
FLOOD_LEVEL_M = 166.4
LEVELS = np.round(np.arange(166.5, 172.01, 0.5), 2)   # flood pictures (below 166.4 nothing is shown)
# Map colours (must match the legends in web/index.html and web/watch.html).
ICE_COLOURS = {1: (31, 111, 191, 235),    # open water: deep blue
               2: (174, 220, 240, 245),   # smooth sheet ice: pale ice blue
               3: (123, 63, 191, 240)}    # rubble / jammed ice: purple
FLOOD_RGBA = (0, 150, 170, 255)           # estimated flooded land: teal (drawn see-through)
# Picture pixel size in web-map metres. At 60.8 N one web-map metre is ~0.49 m on the ground,
# so 20 = ~10 m (the RCM pixel) and 16 = ~8 m. Smaller pictures make the map much smoother.
ICE_PIXEL_M, FLOOD_PIXEL_M = 20, 16
SAFE, POSSIBLE, DANGER = "Safe", "Possible", "High danger"
STATUS = {"Low": SAFE, "Watch": POSSIBLE, "Warning": POSSIBLE, "Critical": DANGER}


def load(name):
    spec = importlib.util.spec_from_file_location(name[:-3], PROJECT_DIR / "scripts" / name)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def merge_gauges():
    """HYDAT + recent provisional data in one file per gauge (HYDAT wins where both exist)."""
    MERGED.mkdir(parents=True, exist_ok=True)
    for stn in ["07OB001", "07OB002", "07OB003"]:
        h = pd.read_csv(RAW / "hydat" / f"{stn}_daily.csv", parse_dates=["date"])
        recent = RAW / "hydat" / f"{stn}_daily_recent.csv"
        if recent.exists():
            r = pd.read_csv(recent, parse_dates=["date"])
            r = r[r["date"] > h["date"].max()]
            h = pd.concat([h, r], ignore_index=True)
        h.to_csv(MERGED / f"{stn}_daily.csv", index=False)
    return {s: MERGED / f"{s}_daily.csv" for s in ["07OB001", "07OB002", "07OB003"]}


def thaw_matrix():
    """Daily thawing degree-days from March 1 (rows = seasons, cols = days since Mar 1)."""
    dd = pd.read_csv(PROC / "ice" / "daily_degree_days.csv", parse_dates=["date"])
    rows = {}
    for s, g in dd.groupby("season"):
        g = g[g["date"] >= pd.Timestamp(f"{s}-03-01")].sort_values("date")
        inc = np.clip(g["tmean_c"].fillna(0).to_numpy(), 0, None)[:200]
        if len(inc) >= 150:
            rows[int(s)] = np.pad(inc, (0, 200 - len(inc)), constant_values=inc[-30:].mean())
    return rows, dd.set_index("date")["tdd"]


def danger_window(year, day, tdd_now, thaw):
    """25/50/75% dates when the thaw total reaches breakup levels, replaying other springs."""
    mar1 = pd.Timestamp(f"{year}-03-01")
    start = max(0, (day - mar1).days)
    hits = []
    for k, inc in thaw.items():
        if k == year:
            continue
        cum = tdd_now + np.cumsum(inc[start:])
        for t in TDD_AT_PEAK:
            idx = np.flatnonzero(cum >= t)
            if len(idx):
                hits.append(start + idx[0] + (0 if tdd_now < t else 0))
    if not hits:
        return None
    q = np.percentile(hits, [25, 50, 75])
    dates = [mar1 + pd.Timedelta(days=int(round(v))) for v in q]
    dates = [max(d, day) for d in dates]
    return dates


if __name__ == "__main__":
    IMG.mkdir(parents=True, exist_ok=True)
    rm = load("41_risk_model.py")
    demo = load("61_export_demo.py")
    fp = load("50_flood_projection.py")
    paths = merge_gauges()
    rm.UPSTREAM, rm.LAKE, rm.TOWN = paths["07OB003"], paths["07OB002"], paths["07OB001"]
    print("Building daily inputs (HYDAT + recent provisional gauge data) ...")
    daily = rm.daily_inputs().set_index("date")
    rows = pd.read_csv(PROC / "risk" / "training_rows.csv", parse_dates=["date"])
    bundle = joblib.load(PROC / "risk" / "risk_model.joblib")
    final_model, spread = bundle["model"], bundle["spread"]
    loyo = pd.read_csv(PROC / "risk" / "loyo_predictions.csv")
    resid = (loyo["peak_level_m"] - loyo["pred_model"]).to_numpy()
    wts = 1.0 / loyo.groupby("year")["year"].transform("size").to_numpy()
    v1 = pd.read_csv(rm.ICE_V1, parse_dates=["time"])
    v2 = pd.read_csv(rm.ICE_V2, parse_dates=["time"])
    offset = float((PROC / "risk" / "hydat_datum_offset.txt").read_text())
    town = pd.read_csv(paths["07OB001"], parse_dates=["date"]).dropna(subset=["level_m"]).set_index("date")["level_m"]
    history = pd.read_csv(PROC / "risk" / "breakup_history.csv", index_col="year")
    winters = pd.read_csv(PROC / "ice" / "winter_summary.csv", index_col="season")
    thaw, tdd_series = thaw_matrix()
    names = {"q_up": "Upstream flow", "q_up_rise7": "Rise in upstream flow (7 days)",
             "lake_anom": "Great Slave Lake level", "thickness_cm": "Ice thickness"}
    scenes_by_day = v1.sort_values("time")

    def chance(median):
        return float((wts * ((median + resid) >= FLOOD_LEVEL_M)).sum() / wts.sum())

    years = {}
    window_check = []
    for year in range(FIRST_YEAR, LAST_DAY.year + 1):
        in_training = year in set(rows["year"])
        model = rm.fit(rows[rows["year"] != year], rm.FEATURES) if in_training else final_model
        days = pd.date_range(f"{year}-01-01", min(pd.Timestamp(f"{year}-06-30"), LAST_DAY))
        out = []
        spring_max, mar1_level = -np.inf, None
        for day in days:
            rec = {"d": day.strftime("%m-%d")}
            tdd = float(tdd_series.get(day, 0.0)) if day >= pd.Timestamp(f"{year}-03-01") else 0.0
            tdd = 0.0 if not np.isfinite(tdd) else tdd
            rec["tdd"] = round(tdd, 1)
            lvl = town.get(day)
            if lvl is not None and np.isfinite(lvl):
                rec["obs"] = round(float(lvl) + offset, 2)
                if day >= pd.Timestamp(f"{year}-03-01"):
                    mar1_level = rec["obs"] if mar1_level is None else mar1_level
                    spring_max = max(spring_max, rec["obs"])
            # --- RCM (only images taken up to this day) ---
            status = rm.rcm_status(day, v1, v2) if year >= 2021 else None
            recent = scenes_by_day[(scenes_by_day["time"] <= day + pd.Timedelta(hours=23)) &
                                   (scenes_by_day["time"] >= day - pd.Timedelta(days=RCM_LOOKBACK_DAYS)) &
                                   (scenes_by_day["jam_zone_coverage"] >= 0.3)]
            if len(recent):
                sc = recent.iloc[-1]
                rec["rcm"] = {"id": sc["scene"], "rubble": round(float(sc["jam_zone_pct_rubble"])),
                              "water": round(float(sc["jam_zone_pct_water"])), "melt": bool(sc["melt_started"])}
            # --- breakup over? (uses only what is known today) ---
            water = max((status or {}).get("water_v2") or 0, (status or {}).get("water_v1") or 0)
            dropped = (mar1_level is not None and tdd >= TDD_AT_PEAK[0] and np.isfinite(spring_max)
                       and spring_max - mar1_level >= RISE_M and rec.get("obs", spring_max) <= spring_max - DROP_M)
            if tdd >= OVER_TDD or (tdd >= TDD_AT_PEAK[0] and water >= rm.RCM_WATER_DOWN) or dropped:
                rec["over"] = True
                rec["status"] = SAFE
                out.append(rec)
                continue
            # --- risk model ---
            x = daily.loc[[day], rm.FEATURES].copy() if day in daily.index else None
            if x is not None:
                x["lake_anom"] = x["lake_anom"].fillna(0.0)
            if x is not None and not x.isna().any(axis=None):
                med = float(model.predict(x)[0])
                p90 = med + spread[0.9]
                level = rm.model_level(med, p90)
                final, why = rm.rcm_adjust(level, status) if year >= 2021 else (level, None)
                contrib = (model.named_steps["standardscaler"].transform(x) * model.named_steps["ridge"].coef_)[0]
                drv = sorted(zip(rm.FEATURES, contrib, x.iloc[0].to_numpy()), key=lambda t: -abs(t[1]))[:3]
                rec.update({"level": final, "model_level": level, "status": STATUS[final],
                            "chance": round(100 * chance(med)), "median": round(med, 2),
                            "p10": round(med + spread[0.1], 2), "p90": round(p90, 2),
                            "base": round(float(model.named_steps["ridge"].intercept_), 2),
                            "all": [[names[f], round(float(v), 2), round(float(c), 2)]
                                    for f, c, v in zip(rm.FEATURES, contrib, x.iloc[0].to_numpy())],
                            "lake_high": bool(x["lake_anom"].iloc[0] >= 0.3),
                            "early": day.strftime("%m-%d") < EARLY_OUTLOOK_BEFORE,
                            "why": [[names[f], round(float(v), 2), round(float(c), 2)] for f, c, v in drv],
                            "rcm_note": why})
            # --- when ---
            win = danger_window(year, day, tdd, thaw)
            if win:
                rec["win"] = [w.strftime("%m-%d") for w in win]
            out.append(rec)
        h = history.loc[year] if year in history.index else None
        peak = h["peak_time"] if h is not None and isinstance(h["peak_time"], str) else None
        years[year] = {
            "days": out,
            "blind": "model never saw this year",
            "peak_level": round(float(h["peak_level_m"]), 2) if h is not None and pd.notna(h["peak_level_m"]) else None,
            "peak_date": peak[:10] if peak else None,
            "flood": bool(h["documented_flood"]) if h is not None else False,
            "freeze_up": str(winters.loc[year + 1, "freeze_up"]) if year + 1 in winters.index else None,
        }
        # Check the danger window against the real peak date (Apr 1 and Apr 15 forecasts).
        if peak and 2002 <= year <= 2024:
            pk = pd.Timestamp(peak[:10])
            for md in ["04-01", "04-15"]:
                r = next((x for x in out if x["d"] == md and "win" in x), None)
                if r:
                    lo, hi = (pd.Timestamp(f"{year}-{r['win'][0]}"), pd.Timestamp(f"{year}-{r['win'][2]}"))
                    window_check.append({"year": year, "issued": md, "inside": lo <= pk <= hi,
                                         "days_off": 0 if lo <= pk <= hi else int(min(abs((pk - lo).days), abs((pk - hi).days)))})
        print(f"{year}: {len(out)} days" + (" (blind: not in training)" if not in_training else ""))

    # The window check uses the full gauge history (2002-2024), not just the years shown.
    window_check = []
    for year in range(2002, 2025):
        if year not in history.index or not isinstance(history.loc[year, "peak_time"], str):
            continue
        pk = pd.Timestamp(history.loc[year, "peak_time"][:10])
        for md in ["04-01", "04-15"]:
            day = pd.Timestamp(f"{year}-{md}")
            t0 = float(tdd_series.get(day, 0.0)) if np.isfinite(tdd_series.get(day, 0.0)) else 0.0
            win = danger_window(year, day, t0, thaw)
            if win:
                inside = win[0] <= pk <= win[2]
                window_check.append({"year": year, "issued": md, "inside": inside,
                                     "days_off": 0 if inside else int(min(abs((pk - win[0]).days), abs((pk - win[2]).days)))})
    wc = pd.DataFrame(window_check)
    check = {md: {"years": int((wc["issued"] == md).sum()), "inside": int(wc[wc["issued"] == md]["inside"].sum()),
                  "median_days_off_when_outside": float(wc[(wc["issued"] == md) & ~wc["inside"]]["days_off"].median())
                  if (~wc[wc["issued"] == md]["inside"]).any() else 0}
             for md in ["04-01", "04-15"]}
    print("\nDanger-window check (did the real peak fall inside the 25-75% window?):", check)

    # --- Images: RCM ice and flood areas ---
    # Own colours for the user view / map explorer, so no colour on that map means two things:
    # red / yellow / green are kept for risk (buildings, places, facilities).
    print("Making RCM pictures ...")
    with rasterio.open(PROC / "corridor" / "river_pixels.tif") as src:
        tf, crs = src.transform, src.crs
    ice_imgs = {}
    for tif in sorted((PROC / "ice_classes").glob("*.tif")):
        classes = rasterio.open(tif).read(1)
        bounds = demo.to_png(classes, tf, crs, IMG / f"w_ice_{tif.stem}.png", ICE_PIXEL_M, ICE_COLOURS)
        ice_imgs[tif.stem] = {"img": f"data/img/w_ice_{tif.stem}.png", "bounds": bounds,
                              "time": pd.to_datetime(tif.stem[:15], format="%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M")}
    print("Making flood pictures ...")
    p = fp.prepare()
    from scipy.ndimage import distance_transform_edt
    near = distance_transform_edt(~p["is_river"]) * abs(p["transform"].a) <= demo.MAX_FLOOD_DISTANCE_M
    curve = pd.read_csv(PROC / "flood_projection" / "impact_curve.csv")
    flood_imgs = {}
    for mouth in fp.MOUTH_LEVELS:
        for lv in LEVELS:
            flooded, _ = fp.flood_extent(p, float(lv), mouth)
            flooded &= near
            name = f"w_flood_{lv:.2f}_{mouth:.2f}"
            bounds = demo.to_png(flooded.astype(np.uint8), p["transform"], p["crs"], IMG / f"{name}.png",
                                 FLOOD_PIXEL_M, {1: FLOOD_RGBA})
            c = curve[(curve["mouth_level_m"] == mouth) & np.isclose(curve["gauge_level_m"], lv)]
            flood_imgs[f"{lv:.2f}|{mouth:.2f}"] = {"img": f"data/img/{name}.png", "bounds": bounds,
                                                   "buildings": int(c["buildings_flooded"].iloc[0]) if len(c) else None}

    map_js = (DATA / "map.js").read_text(encoding="utf-8").split("window.HRFW.map = ", 1)[1].rstrip().rstrip(";")
    # Spread of past forecast errors (each spring weighted equally), used on the page to turn
    # "forecast peak" into "chance the river reaches the level where a place floods".
    order = np.argsort(resid)
    cum = np.cumsum(wts[order]) / wts.sum()
    resid_q = [round(float(np.interp(q, cum, resid[order])), 2) for q in np.linspace(0.025, 0.975, 39)]
    skill = pd.read_csv(PROC / "risk" / "model_skill.csv").to_dict(orient="records")
    out = {"first_year": FIRST_YEAR, "last_day": LAST_DAY.strftime("%Y-%m-%d"),
           "resid_q": resid_q, "skill": skill, "rcm_threshold": rm.RCM_BRIGHT_UP, "melt_tdd": rm.MELT_TDD
           if hasattr(rm, "MELT_TDD") else 20, "watch_m": rm.WATCH_M, "warning_m": rm.WARNING_M,
           "years": years, "window_check": check, "ice": ice_imgs, "flood": flood_imgs,
           "flood_levels": [float(x) for x in LEVELS], "mouths": fp.MOUTH_LEVELS,
           "jam_zone": json.loads(map_js)["jam_zone"], "view": demo.VIEW,
           "tdd_at_peak": TDD_AT_PEAK, "flood_level_m": FLOOD_LEVEL_M}
    (DATA / "watch.js").write_text("window.HRFW = window.HRFW || {};\nwindow.HRFW.watch = "
                                   + json.dumps(out, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Saved {DATA / 'watch.js'} ({(DATA / 'watch.js').stat().st_size / 1e6:.1f} MB)")
