"""
Step 2 (new plan): Ice thickness and degree-days for every winter.

Plain-language method
---------------------
Freezing degree-days (FDD): for each day, how many degrees the daily mean
temperature is BELOW 0 C (a -20 C day adds 20; a +3 C day adds 0). Adding
these up from freeze-up gives the "accumulated freezing degree-days" (AFDD):
a measure of how much cold the river has experienced.

Stefan's equation turns AFDD into an ice-thickness estimate:

    thickness (cm) = ALPHA * sqrt(AFDD)

ALPHA bundles everything Stefan ignores (snow on the ice insulates it, wind,
water flow, ...). Published values (Michel 1971, used widely in river-ice
engineering) are about 1.4-1.7 for an average river with snow cover, lower
for sheltered snowy rivers and higher for windy, snow-free ice. We use 1.5
with a low/high range of 1.2-1.9 to show the uncertainty.
THIS IS AN APPROXIMATION: no measured Hay River ice thicknesses were used
to tune it, so treat the numbers as "relative thickness between winters"
more than exact centimetres.

Thawing degree-days (TDD): the same idea for warm days - degrees ABOVE 0 C,
added up from March 1. It tracks how far spring melt has progressed;
breakup usually happens after a certain amount of warmth has accumulated.

Definitions
-----------
Season "2022" = Sept 1 2021 to July 31 2022 (named by its spring).
Freeze-up = first day from Sept 1 whose following 7-day average is below 0 C.
End of freezing = the day when (sum of FDD - sum of TDD) since freeze-up is
largest, i.e. when the weather turns from net-freezing to net-melting.
Winter AFDD = AFDD from freeze-up to the end of freezing.

Outputs
-------
data/processed/ice/daily_degree_days.csv   one row per day per season
data/processed/ice/winter_summary.csv      one row per winter
outputs/ice/thickness_by_winter.png        estimated max thickness, all winters
outputs/ice/season_<year>.png              one winter vs the long-term range

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\20_ice_thickness.py [season years to plot, e.g. 2022 2026]
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
CLIMATE = PROJECT_DIR / "data" / "raw" / "climate" / "hay_river_daily.csv"
TOWN_GAUGE = PROJECT_DIR / "data" / "raw" / "hydat" / "07OB001_daily.csv"
OUT_DATA = PROJECT_DIR / "data" / "processed" / "ice"
OUT_FIGS = PROJECT_DIR / "outputs" / "ice"

ALPHA = 1.5                      # Stefan coefficient, cm per sqrt(degC-day)
ALPHA_LOW, ALPHA_HIGH = 1.2, 1.9  # plausible range for a snow-covered river
FREEZE_WINDOW_DAYS = 7
MAX_MISSING_DAYS = 10            # winters with more missing days are flagged
FLOOD_YEARS = [1951, 1963, 1974, 1985, 1992, 2003, 2008, 2022]   # GNWT (2025) flood history
TDD_START = "03-01"              # thaw counting starts March 1

# Colours (reference palette): blue = this measure, grey = context, orange = flood years.
BLUE, ORANGE, GREY, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#c3c2b7", "#0b0b0b", "#898781", "#e1e0d9"


def stefan(afdd, alpha=ALPHA):
    return alpha * np.sqrt(np.maximum(afdd, 0))


def one_season(clim, year):
    """Daily degree-days for the season ending in `year` (Sept 1 to July 31)."""
    s = clim[(clim["date"] >= f"{year - 1}-09-01") & (clim["date"] <= f"{year}-07-31")].copy()
    if s["tmean_c"].notna().sum() < 200:
        return None
    t = s["tmean_c"].to_numpy()
    ahead = pd.Series(t).rolling(FREEZE_WINDOW_DAYS, min_periods=5).mean().shift(-(FREEZE_WINDOW_DAYS - 1))
    below = np.flatnonzero(ahead.to_numpy() < 0)
    if len(below) == 0:
        return None
    onset = below[0]

    fdd = np.where(np.arange(len(t)) >= onset, np.clip(-np.nan_to_num(t), 0, None), 0)
    thaw_mask = s["date"] >= pd.Timestamp(f"{year}-{TDD_START}")
    tdd_daily = np.where(thaw_mask, np.clip(np.nan_to_num(t), 0, None), 0)
    net = np.cumsum(np.where(np.arange(len(t)) >= onset, -np.nan_to_num(t), 0))
    end_of_freezing = int(np.argmax(net))

    s["season"] = year
    s["afdd"] = np.cumsum(fdd)
    s["tdd"] = np.cumsum(tdd_daily)
    s["thickness_cm"] = stefan(s["afdd"])
    s["thickness_low_cm"] = stefan(s["afdd"], ALPHA_LOW)
    s["thickness_high_cm"] = stefan(s["afdd"], ALPHA_HIGH)
    s["days_since_sep1"] = (s["date"] - pd.Timestamp(f"{year - 1}-09-01")).dt.days
    s.attrs.update(onset=s["date"].iloc[onset], end_of_freezing=s["date"].iloc[end_of_freezing],
                   afdd_winter=float(s["afdd"].iloc[end_of_freezing]))
    return s


def tdd_on(season_df, month_day):
    row = season_df[season_df["date"] == pd.Timestamp(f"{season_df['season'].iloc[0]}-{month_day}")]
    return float(row["tdd"].iloc[0]) if len(row) else np.nan


def date_tdd_reaches(season_df, amount):
    hit = season_df[season_df["tdd"] >= amount]
    return hit["date"].iloc[0] if len(hit) else pd.NaT


def town_peaks():
    """Spring peak water level and its date at the town gauge (2002-2024)."""
    g = pd.read_csv(TOWN_GAUGE, parse_dates=["date"]).dropna(subset=["level_m"])
    g = g[g["date"].dt.month.isin([4, 5, 6])]
    idx = g.groupby(g["date"].dt.year)["level_m"].idxmax()
    return g.loc[idx].set_index(g.loc[idx, "date"].dt.year)[["date", "level_m"]]


def month_axis(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))


def style(ax):
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(GREY)
    ax.tick_params(colors=MUTED)


def plot_all_winters(summary, path):
    s = summary.dropna(subset=["max_thickness_cm"])
    fig, ax = plt.subplots(figsize=(14, 5.5))
    colours = [ORANGE if y in FLOOD_YEARS else BLUE for y in s.index]
    ax.bar(s.index, s["max_thickness_cm"], color=colours, width=0.75)
    ax.errorbar(s.index, s["max_thickness_cm"],
                yerr=[s["max_thickness_cm"] - s["max_thickness_low_cm"],
                      s["max_thickness_high_cm"] - s["max_thickness_cm"]],
                fmt="none", ecolor=MUTED, elinewidth=0.6, capsize=0)
    for y in FLOOD_YEARS:
        if y in s.index:
            ax.annotate(f"{y} flood", (y, s.loc[y, "max_thickness_high_cm"] + 2), ha="center",
                        fontsize=9, color=INK)
    med = s["max_thickness_cm"].median()
    ax.axhline(med, color=MUTED, linewidth=1, linestyle="--")
    ax.annotate(f"median {med:.0f} cm", (s.index.min(), med + 2), fontsize=9, color=MUTED)
    ax.set_title("Estimated end-of-winter river ice thickness at Hay River "
                 f"(Stefan's equation, alpha = {ALPHA}; whiskers alpha {ALPHA_LOW}-{ALPHA_HIGH})",
                 loc="left", fontsize=12, color=INK)
    ax.set_ylabel("ice thickness (cm)", color=MUTED)
    ax.set_xlabel("winter (named by its spring)", color=MUTED)
    ax.text(0.99, 0.97, "orange = known flood years", transform=ax.transAxes, ha="right",
            va="top", fontsize=9, color=MUTED)
    style(ax)
    plt.tight_layout()
    plt.savefig(path, dpi=110)
    plt.close(fig)


def plot_season(daily, summary, year, peaks, path):
    others = daily[daily["season"] != year]
    this = daily[daily["season"] == year]
    if this.empty:
        print(f"  no data for season {year}")
        return
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))

    # Left: ice thickness through the winter.
    ax = axes[0]
    q = others.groupby("days_since_sep1")["thickness_cm"].quantile([0.1, 0.5, 0.9]).unstack()
    q = q.loc[q.index <= 300]
    base = pd.Timestamp(f"{year - 1}-09-01")
    x = base + pd.to_timedelta(q.index, unit="D")
    ax.fill_between(x, q[0.1], q[0.9], color=GREY, alpha=0.5, linewidth=0,
                    label="other winters (10th-90th percentile)")
    ax.plot(x, q[0.5], color=MUTED, linewidth=1.5, label="other winters (median)")
    t = this[this["days_since_sep1"] <= 300]
    ax.plot(t["date"], t["thickness_cm"], color=BLUE, linewidth=2, label=f"{year}")
    ax.fill_between(t["date"], t["thickness_low_cm"], t["thickness_high_cm"], color=BLUE,
                    alpha=0.15, linewidth=0, label=f"{year}, alpha {ALPHA_LOW}-{ALPHA_HIGH}")
    ax.set_title(f"Estimated ice thickness, winter {year - 1}-{year}", loc="left", color=INK)
    ax.set_ylabel("ice thickness (cm)", color=MUTED)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    style(ax)
    month_axis(ax)

    # Right: spring thaw (TDD from March 1).
    ax = axes[1]
    spring = daily[(daily["date"].dt.month.isin([3, 4, 5, 6]))].copy()
    spring["doy"] = spring["date"].dt.dayofyear
    so = spring[spring["season"] != year]
    q2 = so.groupby("doy")["tdd"].quantile([0.1, 0.5, 0.9]).unstack()
    x2 = pd.Timestamp(f"{year}-01-01") + pd.to_timedelta(q2.index - 1, unit="D")
    ax.fill_between(x2, q2[0.1], q2[0.9], color=GREY, alpha=0.5, linewidth=0,
                    label="other springs (10th-90th percentile)")
    ax.plot(x2, q2[0.5], color=MUTED, linewidth=1.5, label="other springs (median)")
    st = spring[spring["season"] == year]
    ax.plot(st["date"], st["tdd"], color=BLUE, linewidth=2, label=f"{year}")
    if year in peaks.index:
        pk = peaks.loc[year, "date"]
        ax.axvline(pk, color=ORANGE, linewidth=1.5)
        ax.annotate(f"town gauge peak\n{pk:%b %d} ({peaks.loc[year, 'level_m']:.2f} m)",
                    (pk, ax.get_ylim()[1] * 0.85), xytext=(6, 0), textcoords="offset points",
                    fontsize=9, color=INK)
    ax.set_title(f"Spring thaw: thawing degree-days since March 1, {year}", loc="left", color=INK)
    ax.set_ylabel("thawing degree-days (degC-days)", color=MUTED)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    style(ax)
    month_axis(ax)

    plt.tight_layout()
    plt.savefig(path, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_FIGS.mkdir(parents=True, exist_ok=True)
    clim = pd.read_csv(CLIMATE, parse_dates=["date"])
    peaks = town_peaks()

    seasons, rows = [], []
    for year in range(clim["date"].dt.year.min() + 1, clim["date"].dt.year.max() + 1):
        s = one_season(clim, year)
        if s is None:
            continue
        seasons.append(s)
        winter = s[(s["date"] >= s.attrs["onset"]) & (s["date"] <= f"{year}-04-30")]
        missing = int(winter["tmean_c"].isna().sum())
        rows.append({
            "season": year,
            "freeze_up": s.attrs["onset"].date(),
            "end_of_freezing": s.attrs["end_of_freezing"].date(),
            "afdd_winter": round(s.attrs["afdd_winter"]),
            "max_thickness_cm": round(stefan(s.attrs["afdd_winter"]), 1),
            "max_thickness_low_cm": round(stefan(s.attrs["afdd_winter"], ALPHA_LOW), 1),
            "max_thickness_high_cm": round(stefan(s.attrs["afdd_winter"], ALPHA_HIGH), 1),
            "tdd_apr15": round(tdd_on(s, "04-15"), 1),
            "tdd_may01": round(tdd_on(s, "05-01"), 1),
            "tdd_may15": round(tdd_on(s, "05-15"), 1),
            "date_tdd_50": date_tdd_reaches(s, 50),
            "date_tdd_100": date_tdd_reaches(s, 100),
            "april_mean_c": round(s[s["date"].dt.month == 4]["tmean_c"].mean(), 1),
            "max_snow_on_ground_cm": s["snow_on_ground_cm"].max(),
            "winter_snowfall_cm": round(s[s["date"].dt.month.isin([11, 12, 1, 2, 3])]["snow_cm"].sum(), 0),
            "missing_days": missing,
            "data_ok": missing <= MAX_MISSING_DAYS,
            "flood_year": year in FLOOD_YEARS,
        })
    daily = pd.concat(seasons)[["season", "date", "days_since_sep1", "tmean_c", "afdd", "tdd",
                                "thickness_cm", "thickness_low_cm", "thickness_high_cm"]]
    summary = pd.DataFrame(rows).set_index("season")
    # Thawing degree-days on the day the town gauge peaked (breakup), 2002-2024.
    summary["gauge_peak_date"] = peaks["date"].dt.date
    summary["gauge_peak_level_m"] = peaks["level_m"]
    tdd_at_peak = {}
    for year, row in peaks.iterrows():
        d = daily[(daily["season"] == year) & (daily["date"] == row["date"])]
        if len(d):
            tdd_at_peak[year] = round(float(d["tdd"].iloc[0]), 1)
    summary["tdd_at_gauge_peak"] = pd.Series(tdd_at_peak)

    daily.to_csv(OUT_DATA / "daily_degree_days.csv", index=False)
    summary.to_csv(OUT_DATA / "winter_summary.csv")
    print(f"Winters computed: {len(summary)} ({summary.index.min()}-{summary.index.max()}), "
          f"{(~summary['data_ok']).sum()} flagged for missing data: "
          f"{summary.index[~summary['data_ok']].tolist()}")
    ok = summary[summary["data_ok"]]
    print(f"Winter AFDD: median {ok['afdd_winter'].median():.0f}, "
          f"range {ok['afdd_winter'].min():.0f}-{ok['afdd_winter'].max():.0f} degC-days")
    print(f"Max ice thickness (alpha {ALPHA}): median {ok['max_thickness_cm'].median():.0f} cm, "
          f"range {ok['max_thickness_cm'].min():.0f}-{ok['max_thickness_cm'].max():.0f} cm")
    print("\nFlood years vs all winters (percentile of max thickness / TDD on May 1):")
    for y in FLOOD_YEARS:
        if y in ok.index:
            pt = (ok["max_thickness_cm"] < ok.loc[y, "max_thickness_cm"]).mean() * 100
            pm = (ok["tdd_may01"] < ok.loc[y, "tdd_may01"]).mean() * 100
            print(f"  {y}: thickness {ok.loc[y, 'max_thickness_cm']:.0f} cm ({pt:.0f}th pct), "
                  f"TDD May 1 {ok.loc[y, 'tdd_may01']:.0f} ({pm:.0f}th pct)")
    tp = summary["tdd_at_gauge_peak"].dropna()
    print(f"\nThawing degree-days on the day of the spring peak at the town gauge (2002-2024): "
          f"median {tp.median():.0f}, middle half {tp.quantile(0.25):.0f}-{tp.quantile(0.75):.0f}")

    plot_all_winters(ok, OUT_FIGS / "thickness_by_winter.png")
    for year in [int(a) for a in sys.argv[1:]] or [2022, int(summary.index.max())]:
        plot_season(daily, summary, year, peaks, OUT_FIGS / f"season_{year}.png")
    print(f"\nTables in {OUT_DATA}\nCharts in {OUT_FIGS}")
