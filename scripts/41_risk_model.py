"""
Step 4b (new plan): Breakup flood-risk model.

What it predicts
----------------
The PEAK spring water level at the town gauge (WSC 07OB001, metres above sea
level, GNWT Table 16), using only what is known on a given day before the
peak. Training rows: every day from April 1 until the day before that
spring's peak, for every year with data (about 1975-2024). Each year counts
equally, however many days it contributes.

Features (all known on the day):
    thickness_cm   Stefan ice thickness so far (step 2)
    snowfall_cm    winter snowfall Nov-Mar (more snow -> more meltwater)
    tdd            thawing degree-days since March 1 (how far melt has gone)
    tdd_7d         thawing degree-days in the last 7 days (how FAST it is warming)
    q_up           Hay River flow upstream at Meander River (07OB003), m3/s
    q_up_rise7     change in that flow over the last 7 days
    lake_anom      Great Slave Lake level (07OB002) minus its long-term average

Model: ridge regression (a linear model with a mild penalty that keeps the
weights stable when there are few years). Each feature gets one weight, so
it is easy to explain which factors push the forecast up or down.

Testing (leave-one-year-out): for each year, train on all OTHER years and
predict that year day by day. Errors are summarised by how many days before
the peak the forecast was made. Two baselines use the same test:
    climatology       always predict the average peak of the other years
    upstream flow     linear model on q_up and q_up_rise7 only

Uncertainty: the spread (10th-90th percentile) of ALL leave-one-year-out
errors before the peak, each spring weighted equally, gives the range around
each forecast. (Splitting it by melt progress left too few years per group.)

Risk levels (from the GNWT flood history - documented floods happened with
gauge peaks between 166.4 m and 170.9 m, but some years above 168 m did not
flood because the jam formed elsewhere):
    Watch     the 90th-percentile forecast reaches WATCH_M    (166.4)
    Warning   the median forecast reaches WATCH_M, or the 90th percentile
              reaches WARNING_M (167.75, the 1985/1992 flood levels)
    Critical  the median forecast reaches WARNING_M
RCM adjustment (latest scene within RCM_MAX_AGE_DAYS): rubble ice building up
in the jam zone raises the level by one step; a jam zone that is mostly open
water lowers it by one step (the ice has gone, so jamming is over).

Outputs
-------
data/processed/risk/training_rows.csv
data/processed/risk/loyo_predictions.csv
data/processed/risk/model_skill.csv
data/processed/risk/risk_model.joblib
data/processed/risk/replay_2022.csv
outputs/risk/*.png

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\41_risk_model.py
"""

from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROC = PROJECT_DIR / "data" / "processed"
HISTORY = PROC / "risk" / "breakup_history.csv"
DEGREE_DAYS = PROC / "ice" / "daily_degree_days.csv"
WINTERS = PROC / "ice" / "winter_summary.csv"
UPSTREAM = PROJECT_DIR / "data" / "raw" / "hydat" / "07OB003_daily.csv"
LAKE = PROJECT_DIR / "data" / "raw" / "hydat" / "07OB002_daily.csv"
TOWN = PROJECT_DIR / "data" / "raw" / "hydat" / "07OB001_daily.csv"
ICE_V1 = PROC / "ice_scene_summary.csv"
ICE_V2 = PROC / "ice_scene_summary_v2.csv"
OUT = PROC / "risk"
FIGS = PROJECT_DIR / "outputs" / "risk"

# Chosen by comparing feature sets with the same leave-one-year-out test
# (all 7 candidate factors did WORSE than these 4: too many factors for ~46
# springs). Snowfall and the thaw-degree-day factors were dropped.
FEATURES = ["q_up", "q_up_rise7", "lake_anom", "thickness_cm"]
BASELINE_FEATURES = ["q_up", "q_up_rise7"]
RIDGE_ALPHA = 1.0
SEASON_START = "04-01"
LEADS = [21, 14, 7, 3, 1]                 # days before the peak, for the skill table
WATCH_M, WARNING_M = 166.4, 167.75
RCM_MAX_AGE_DAYS = 3
# RCM rules, set from the POSITIVE control (2022 flood) and NEGATIVE control
# (2023, normal breakup) - see control_threshold():
#   * "% rough/rubble ice in the jam zone during melt, before the peak" separated
#     the two years cleanly (2022: 91-96%, 2023: 45-76%), so the raise threshold
#     is set halfway between them and then checked on 2021 and 2024;
#   * "% new rubble since late winter" did NOT separate them (2023 had more), so
#     that rule is switched off (RCM_RUBBLE_UP = None).
POSITIVE_CONTROL, NEGATIVE_CONTROL = 2022, 2023
CHECK_YEARS = [2021, 2024]
RCM_RUBBLE_UP = None       # switched off (see above)
RCM_BRIGHT_UP = 85.0       # replaced at run time by control_threshold()
RCM_WATER_DOWN = 50.0      # % open water in the jam zone -> lower one level
_saved = Path(__file__).resolve().parent.parent / "data" / "processed" / "risk" / "rcm_threshold.txt"
if _saved.exists():          # other scripts that load this file use the control-based value
    RCM_BRIGHT_UP = float(_saved.read_text())
LEVELS = ["Low", "Watch", "Warning", "Critical"]

INK, MUTED, GRID, AXIS = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#c3c2b7"
LEVEL_COLOURS = {"Low": "#0ca30c", "Watch": "#fab219", "Warning": "#ec835a", "Critical": "#d03b3b"}


# --- Features ---------------------------------------------------------------

def daily_inputs():
    """One row per calendar day with every feature (before choosing rows)."""
    dd = pd.read_csv(DEGREE_DAYS, parse_dates=["date"])
    dd = dd.sort_values("date").drop_duplicates("date")
    dd["tdd_7d"] = dd.groupby("season")["tdd"].diff(7).fillna(dd["tdd"])
    winters = pd.read_csv(WINTERS, index_col="season")
    dd["snowfall_cm"] = dd["season"].map(winters["winter_snowfall_cm"])

    up = pd.read_csv(UPSTREAM, parse_dates=["date"]).set_index("date")["discharge_m3s"]
    up = up.reindex(pd.date_range(up.index.min(), up.index.max())).interpolate(limit=5)
    lake = pd.read_csv(LAKE, parse_dates=["date"]).set_index("date")["level_m"]
    lake = lake.reindex(pd.date_range(lake.index.min(), lake.index.max())).interpolate(limit=10)

    d = dd.set_index("date")
    d["q_up"] = up.reindex(d.index)
    d["q_up_rise7"] = d["q_up"] - up.reindex(d.index - pd.Timedelta(days=7)).to_numpy()
    d["lake_anom"] = lake.reindex(d.index) - lake.mean()
    return d.rename(columns={"thickness_cm": "thickness_cm"}).reset_index()


def training_rows(daily, history):
    rows = []
    for year, h in history.iterrows():
        if pd.isna(h["peak_level_m"]) or pd.isna(h["peak_date"]):
            continue
        start = pd.Timestamp(f"{year}-{SEASON_START}")
        days = daily[(daily["date"] >= start) & (daily["date"] < h["peak_date"].normalize())].copy()
        if days.empty:
            continue
        days["year"] = year
        days["days_to_peak"] = (h["peak_date"].normalize() - days["date"]).dt.days
        days["peak_level_m"] = h["peak_level_m"]
        days["documented_flood"] = h["documented_flood"]
        rows.append(days)
    rows = pd.concat(rows)
    # Lake level has a 1971-1983 gap: fill with the average (anomaly 0) and flag it.
    rows["lake_filled"] = rows["lake_anom"].isna()
    rows["lake_anom"] = rows["lake_anom"].fillna(0.0)
    keep = rows.dropna(subset=FEATURES)
    return keep


def make_model(features):
    model = Ridge(alpha=RIDGE_ALPHA) if len(features) > 2 else LinearRegression()
    return make_pipeline(StandardScaler(), model)


def fit(rows, features):
    weights = 1.0 / rows.groupby("year")["year"].transform("size")
    return make_model(features).fit(rows[features], rows["peak_level_m"], **{
        list(make_model(features).named_steps)[-1] + "__sample_weight": weights})


# --- Risk level -------------------------------------------------------------

def model_level(median, p90):
    if median >= WARNING_M:
        return "Critical"
    if median >= WATCH_M or p90 >= WARNING_M:
        return "Warning"
    if p90 >= WATCH_M:
        return "Watch"
    return "Low"


def rcm_status(day, v1, v2):
    """Latest RCM view of the jam zone within RCM_MAX_AGE_DAYS before `day`."""
    recent2 = v2[(v2["time"] <= day + pd.Timedelta(hours=23)) &
                 (v2["time"] >= day - pd.Timedelta(days=RCM_MAX_AGE_DAYS)) &
                 (v2["jam_zone_classified_pct"] >= 30)]
    recent1 = v1[(v1["time"] <= day + pd.Timedelta(hours=23)) &
                 (v1["time"] >= day - pd.Timedelta(days=RCM_MAX_AGE_DAYS)) &
                 (v1["jam_zone_coverage"] >= 0.3)]
    if recent2.empty and recent1.empty:
        return None
    out = {}
    if len(recent2):
        r = recent2.sort_values("time").iloc[-1]
        out.update(scene_v2=r["scene"], rubble_v2=r["jam_zone_pct_new"], water_v2=r["jam_zone_pct_open"])
    if len(recent1):
        r = recent1.sort_values("time").iloc[-1]
        out.update(scene_v1=r["scene"], bright_v1=r["jam_zone_pct_rubble"], water_v1=r["jam_zone_pct_water"],
                   melt=r["melt_started"])
    return out


def rcm_adjust(level, status):
    if not status:
        return level, "no recent RCM image of the jam zone"
    i = LEVELS.index(level)
    water = max(status.get("water_v2") or 0, status.get("water_v1") or 0)
    if water >= RCM_WATER_DOWN:
        return LEVELS[max(i - 1, 0)], f"RCM: jam zone {water:.0f}% open water - ice has cleared"
    if RCM_RUBBLE_UP is not None and (status.get("rubble_v2") or 0) >= RCM_RUBBLE_UP:
        return LEVELS[min(i + 1, 3)], f"RCM: {status['rubble_v2']:.0f}% new rubble ice in jam zone"
    if status.get("melt") and (status.get("bright_v1") or 0) >= RCM_BRIGHT_UP:
        return LEVELS[min(i + 1, 3)], f"RCM: {status['bright_v1']:.0f}% rough/rubble ice in jam zone during melt"
    return level, "RCM: no sign of ice building up in the jam zone"


# --- Charts -----------------------------------------------------------------

def control_threshold(v1, history):
    """
    Jam-zone '% rough/rubble ice' threshold from the positive and negative
    controls: scenes during melt, up to the day of each year's peak, that see
    at least 30% of the jam zone. Threshold = halfway between the control
    year's highest value and the flood year's lowest value.
    """
    def melt_scenes(year):
        peak = pd.Timestamp(history.loc[year, "peak_time"]).normalize()
        s = v1[(v1["year"] == year) & v1["melt_started"] & (v1["jam_zone_coverage"] >= 0.3)
               & (v1["time"] <= peak + pd.Timedelta(hours=23))]
        return s["jam_zone_pct_rubble"]
    flood, normal = melt_scenes(POSITIVE_CONTROL), melt_scenes(NEGATIVE_CONTROL)
    threshold = round((flood.min() + normal.max()) / 2, 1)
    print("\nRCM control comparison, % rough/rubble ice in the jam zone during melt before the peak:")
    print(f"  {POSITIVE_CONTROL} (flood):     {flood.min():.0f}-{flood.max():.0f}% ({len(flood)} images)")
    print(f"  {NEGATIVE_CONTROL} (no flood):  {normal.min():.0f}-{normal.max():.0f}% ({len(normal)} images)")
    print(f"  -> threshold {threshold:.1f}% (halfway). Check years:")
    for y in CHECK_YEARS:
        s = melt_scenes(y) if y in history.index and pd.notna(history.loc[y, "peak_time"]) else \
            v1[(v1["year"] == y) & v1["melt_started"] & (v1["jam_zone_coverage"] >= 0.3)]["jam_zone_pct_rubble"]
        print(f"  {y}: {len(s)} images, {(s >= threshold).sum()} above threshold "
              f"(values {', '.join(f'{v:.0f}' for v in s)})")
    return threshold


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

    history = pd.read_csv(HISTORY, index_col="year")
    history["peak_date"] = pd.to_datetime(history["peak_time"], errors="coerce")
    town = pd.read_csv(TOWN, parse_dates=["date"]).dropna(subset=["level_m"])
    for year in history.index[history["peak_date"].isna()]:
        s = town[(town["date"].dt.year == year) & town["date"].dt.month.isin([4, 5, 6])]
        if len(s):
            history.loc[year, "peak_date"] = s.loc[s["level_m"].idxmax(), "date"]
    daily = daily_inputs()
    rows = training_rows(daily, history)
    rows.to_csv(OUT / "training_rows.csv", index=False)
    years = sorted(rows["year"].unique())
    print(f"Training rows: {len(rows):,} days from {len(years)} springs ({years[0]}-{years[-1]}); "
          f"lake level filled with average in {rows.loc[rows['lake_filled'], 'year'].nunique()} springs")

    # --- Leave-one-year-out ----------------------------------------------------
    preds = []
    for year in years:
        train, test = rows[rows["year"] != year], rows[rows["year"] == year].copy()
        test["pred_model"] = fit(train, FEATURES).predict(test[FEATURES])
        test["pred_upstream"] = fit(train, BASELINE_FEATURES).predict(test[BASELINE_FEATURES])
        test["pred_climatology"] = train.groupby("year")["peak_level_m"].first().mean()
        preds.append(test)
    preds = pd.concat(preds)
    preds.to_csv(OUT / "loyo_predictions.csv", index=False)

    skill = []
    for lead in LEADS:
        at = preds[preds["days_to_peak"] == lead]
        row = {"days_before_peak": lead, "springs": len(at)}
        for m in ["model", "upstream", "climatology"]:
            err = at[f"pred_{m}"] - at["peak_level_m"]
            row[f"MAE_{m}"] = round(err.abs().mean(), 2)
        floods = at[at["documented_flood"]]
        row["flood_years_tested"] = len(floods)
        row["flood_years_median_ge_watch"] = int((floods["pred_model"] >= WATCH_M).sum())
        skill.append(row)
    skill = pd.DataFrame(skill)
    skill.to_csv(OUT / "model_skill.csv", index=False)
    print("\nLeave-one-year-out error in the predicted peak level (mean absolute error, metres):")
    print(skill.to_string(index=False))

    # Uncertainty: weighted quantiles of all leave-one-year-out errors.
    preds["resid"] = preds["peak_level_m"] - preds["pred_model"]
    w = 1.0 / preds.groupby("year")["year"].transform("size")
    order = np.argsort(preds["resid"].to_numpy())
    cum = np.cumsum(w.to_numpy()[order]) / w.sum()
    resid_sorted = preds["resid"].to_numpy()[order]
    spread = {q: float(np.interp(q, cum, resid_sorted)) for q in (0.1, 0.5, 0.9)}
    print(f"\nForecast range: actual peak minus forecast, 10th / 50th / 90th percentile: "
          f"{spread[0.1]:+.2f} / {spread[0.5]:+.2f} / {spread[0.9]:+.2f} m")

    # How often each risk level was issued 7 and 3 days ahead (model only, no RCM).
    print("\nRisk level issued by the model alone (each spring tested without itself):")
    for lead in [7, 3]:
        at = preds[preds["days_to_peak"] == lead].copy()
        at["level"] = [model_level(mu, mu + spread[0.9]) for mu in at["pred_model"]]
        at["group"] = np.where(at["documented_flood"], "documented flood",
                               np.where(at["peak_level_m"] >= WATCH_M, "high water, no flood", "normal"))
        table = pd.crosstab(at["group"], at["level"]).reindex(columns=LEVELS, fill_value=0)
        print(f"  {lead} days before the peak:\n" + table.to_string())

    # --- Final model (all years) and what drives it --------------------------
    final = fit(rows, FEATURES)
    coefs = final.named_steps["ridge"].coef_
    print("\nWhat pushes the forecast up (+) or down (-): metres per 1 standard deviation of each factor")
    for f, c in sorted(zip(FEATURES, coefs), key=lambda t: -abs(t[1])):
        print(f"  {f:13s} {c:+.2f}")
    joblib.dump({"model": final, "features": FEATURES, "spread": spread,
                 "watch_m": WATCH_M, "warning_m": WARNING_M}, OUT / "risk_model.joblib")

    # --- 2022 replay -------------------------------------------------------------
    v1 = pd.read_csv(ICE_V1, parse_dates=["time"])
    v2 = pd.read_csv(ICE_V2, parse_dates=["time"])
    RCM_BRIGHT_UP = control_threshold(v1, history)
    (OUT / "rcm_threshold.txt").write_text(f"{RCM_BRIGHT_UP}\n")
    test22 = preds[preds["year"] == 2022].set_index("date")
    model_wo_2022 = fit(rows[rows["year"] != 2022], FEATURES)
    replay = []
    for day in pd.date_range("2022-04-15", "2022-05-20"):
        row = daily[daily["date"] == day]
        x = row[FEATURES].fillna({"lake_anom": 0.0})
        if row.empty or x.isna().any(axis=None):
            continue
        # Before the peak use the forecast from the model that never saw 2022.
        if day in test22.index:
            median = float(test22.loc[day, "pred_model"])
        else:
            median = float(model_wo_2022.predict(x)[0])
        p10, p90 = median + spread[0.1], median + spread[0.9]
        level = model_level(median, p90)
        status = rcm_status(day, v1, v2)
        final_level, why = rcm_adjust(level, status)
        obs = town[town["date"] == day]["level_m"]
        replay.append({"date": day.date(), "tdd": round(float(row["tdd"].iloc[0]), 1),
                       "q_up": float(x["q_up"].iloc[0]), "forecast_p10": round(p10, 2),
                       "forecast_median": round(median, 2), "forecast_p90": round(p90, 2),
                       "model_level": level, "rcm_note": why, "risk_level": final_level,
                       "observed_daily_level_m": round(float(obs.iloc[0]) + float(
                           (OUT / "hydat_datum_offset.txt").read_text()), 2) if len(obs) else None})
    replay = pd.DataFrame(replay)
    replay.to_csv(OUT / "replay_2022.csv", index=False)
    print("\n2022 replay (forecast of the spring peak made each day, model trained without 2022):")
    print(replay[["date", "tdd", "q_up", "forecast_median", "forecast_p90", "model_level",
                  "risk_level", "rcm_note"]].to_string(index=False))

    # --- Charts --------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 5))
    for m, colour, label in [("model", BLUE, "risk model (all factors)"),
                             ("upstream", ORANGE, "upstream flow only"),
                             ("climatology", MUTED, "long-term average")]:
        ax.plot(skill["days_before_peak"], skill[f"MAE_{m}"], marker="o", color=colour, label=label,
                linewidth=2, markersize=8)
    ax.invert_xaxis()
    ax.set_xlabel("days before the peak when the forecast was made", color=MUTED)
    ax.set_ylabel("average error in peak level (m)", color=MUTED)
    ax.set_title("How accurate is the peak-level forecast? (each spring tested without itself)",
                 loc="left", color=INK, fontsize=11)
    ax.legend(frameon=False)
    style(ax)
    plt.tight_layout(); plt.savefig(FIGS / "forecast_skill.png", dpi=110); plt.close(fig)

    r = replay.copy(); r["date"] = pd.to_datetime(r["date"])
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.fill_between(r["date"], r["forecast_p10"], r["forecast_p90"], color=BLUE, alpha=0.15,
                    linewidth=0, label="forecast range (10-90%)")
    ax.plot(r["date"], r["forecast_median"], color=BLUE, linewidth=2, label="forecast peak level")
    ax.plot(r["date"], r["observed_daily_level_m"], color=INK, linewidth=1.5,
            label="observed daily level (HYDAT, converted)")
    ax.axhline(history.loc[2022, "peak_level_m"], color=INK, linestyle=":", linewidth=1)
    ax.annotate(f"actual 2022 peak {history.loc[2022, 'peak_level_m']:.2f} m (instantaneous)",
                (r["date"].iloc[-1], history.loc[2022, "peak_level_m"] + 0.1), ha="right",
                fontsize=9, color=INK)
    for y, name in [(WATCH_M, "Watch / documented flooding from"), (WARNING_M, "Warning: 1985/1992 flood level")]:
        ax.axhline(y, color=GREY, linewidth=1)
        ax.annotate(name, (r["date"].iloc[-1], y + 0.08), ha="right", fontsize=8, color=MUTED)
    for _, row in r.iterrows():
        ax.axvspan(row["date"] - pd.Timedelta(hours=12), row["date"] + pd.Timedelta(hours=12),
                   ymin=0, ymax=0.04, color=LEVEL_COLOURS[row["risk_level"]], linewidth=0)
    ax.axvline(pd.Timestamp("2022-05-11"), color=ORANGE, linewidth=1.5)
    ax.annotate("evacuation\nMay 11", (pd.Timestamp("2022-05-11"), ax.get_ylim()[0] + 0.5),
                xytext=(4, 0), textcoords="offset points", fontsize=9, color=INK)
    ax.set_ylabel("water level at town gauge (m above sea level)", color=MUTED)
    ax.set_title("2022 replay: daily forecast of the spring peak (bottom strip = risk level)",
                 loc="left", color=INK, fontsize=11)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    from matplotlib.patches import Patch
    lines = ax.legend(frameon=False, loc="upper left", fontsize=9)
    ax.add_artist(lines)
    ax.legend(handles=[Patch(color=LEVEL_COLOURS[l], label=l) for l in LEVELS], title="risk level",
              frameon=False, loc="center left", fontsize=8, title_fontsize=8)
    style(ax)
    plt.tight_layout(); plt.savefig(FIGS / "replay_2022.png", dpi=110); plt.close(fig)
    print(f"\nOutputs in {OUT} and {FIGS}")
