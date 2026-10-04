"""
Step 11a (pitch): make the pictures for the pitch deck from REAL project results.

  * Charts (matplotlib), all numbers read from project files:
      chart_rcm_controls.png   jam-zone rubble ice % per RCM image, 2022 flood vs 2023 normal,
                               with the 83.7% threshold (data/processed/ice_scene_summary.csv)
      chart_leadtime_2022.png  daily risk status from Mar 1 to the 2022 peak (web/data/watch.js)
  * Screenshots of the real web app (Edge, headless, 2x sharp):
      shot_compare.png         judges' page: 2022 flood year vs 2023 normal year at the peak
      shot_flood2022.png       judges' page: 2022 map at the peak (left map only)
      shot_explorer.png        map explorer, May 8 2022 (sidebar + Hay River map)
      shot_canada.png          map explorer zoomed out (all sites)
      shot_places.png          user view: "Places that may be affected" card
  * results.json: every number quoted in the deck and script, with where it came from.
  * Fonts: Lato and Noto Sans .ttf files (for the charts, and to install before presenting).

Output: outputs/pitch_assets/

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\80_pitch_assets.py
"""

import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd
import requests
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROC = PROJECT_DIR / "data" / "processed"
WEB = PROJECT_DIR / "web"
OUT = PROJECT_DIR / "outputs" / "pitch_assets"
FONTS = OUT / "fonts"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

NAVY, DEEP, LIGHT, RED = "#26374A", "#0B1A2E", "#F5F6F8", "#EB2D37"
SAFE, POSSIBLE, DANGER, NONE = "#2e7d4f", "#f2b705", "#eb2d37", "#c5ccd4"
WATCH_M, WARNING_M = 166.4, 167.75
FONT_URLS = {
    "Lato-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/lato/Lato-Regular.ttf",
    "Lato-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/lato/Lato-Bold.ttf",
    "NotoSans.ttf": "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans%5Bwdth,wght%5D.ttf",
}


def get_fonts():
    FONTS.mkdir(parents=True, exist_ok=True)
    for name, url in FONT_URLS.items():
        p = FONTS / name
        if not p.exists():
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            p.write_bytes(r.content)
        font_manager.fontManager.addfont(str(p))
    plt.rcParams["font.family"] = "Lato"


def load_js(name, var):
    t = (WEB / "data" / name).read_text(encoding="utf-8")
    return json.loads(t.split(f"window.HRFW.{var} = ", 1)[1].rstrip().rstrip(";"))


def model_level(m, p90):
    if m >= WARNING_M:
        return "Critical"
    if m >= WATCH_M or p90 >= WARNING_M:
        return "Warning"
    if p90 >= WATCH_M:
        return "Watch"
    return "Low"


def results():
    """Every number used in the pitch, recomputed from project files."""
    R = {}
    skill = pd.read_csv(PROC / "risk" / "model_skill.csv").set_index("days_before_peak")
    R["mae_7d"] = {k: float(skill.loc[7, f"MAE_{k}"]) for k in ["model", "upstream", "climatology"]}
    R["springs_tested"] = int(skill.loc[7, "springs"])
    # Risk level a week before the peak, exactly as scripts/41_risk_model.py does it.
    preds = pd.read_csv(PROC / "risk" / "loyo_predictions.csv")
    preds["resid"] = preds["peak_level_m"] - preds["pred_model"]
    w = 1.0 / preds.groupby("year")["year"].transform("size")
    order = np.argsort(preds["resid"].to_numpy())
    cum = np.cumsum(w.to_numpy()[order]) / w.sum()
    p90 = float(np.interp(0.9, cum, preds["resid"].to_numpy()[order]))
    at = preds[preds["days_to_peak"] == 7].copy()
    at["level"] = [model_level(mu, mu + p90) for mu in at["pred_model"]]
    flood = at[at["documented_flood"]]
    normal = at[~at["documented_flood"] & (at["peak_level_m"] < WATCH_M)]
    R["week_ahead"] = {
        "flood_years": {str(int(y)): l for y, l in zip(flood["year"], flood["level"])},
        "flood_years_warning_or_higher": int(flood["level"].isin(["Warning", "Critical"]).sum()),
        "flood_years_tested": len(flood),
        "normal_springs": len(normal),
        "normal_springs_warning": int((normal["level"] == "Warning").sum()),
        "normal_springs_critical": int((normal["level"] == "Critical").sum()),
    }
    W = load_js("watch.js", "watch")
    R["danger_window"] = W["window_check"]
    R["rcm_threshold"] = W["rcm_threshold"]
    days = W["years"]["2022"]["days"]
    first = lambda st: next((f"2022-{d['d']}" for d in days if d.get("status") in st and not d.get("over")), None)
    R["replay_2022"] = {"first_warning": first(("Possible", "High danger")), "first_high_danger": first(("High danger",)),
                        "peak": W["years"]["2022"]["peak_date"], "peak_level_m": W["years"]["2022"]["peak_level"]}
    days21 = W["years"]["2021"]["days"]
    R["false_alarm_2021"] = {"first_high_danger": next((f"2021-{d['d']}" for d in days21 if d.get("status") == "High danger"), None),
                             "peak_level_m": W["years"]["2021"]["peak_level"], "flood": W["years"]["2021"]["flood"]}
    # RCM controls.
    v1 = pd.read_csv(PROC / "ice_scene_summary.csv", parse_dates=["time"])
    hist = pd.read_csv(PROC / "risk" / "breakup_history.csv").set_index("year")
    ctrl = {}
    for y in (2022, 2023):
        peak = pd.Timestamp(hist.loc[y, "peak_time"]).normalize()
        s = v1[(v1["year"] == y) & v1["melt_started"] & (v1["jam_zone_coverage"] >= 0.3)
               & (v1["time"] <= peak + pd.Timedelta(hours=23))].sort_values("time")
        ctrl[y] = s
        R[f"rcm_{y}"] = {"min": round(float(s["jam_zone_pct_rubble"].min()), 1),
                         "max": round(float(s["jam_zone_pct_rubble"].max()), 1), "images": len(s)}
    # Blind test: the LOCKED predictions only (outcomes are not checked).
    bt = PROJECT_DIR / "outputs" / "blind_test"
    rows = []
    for f in sorted(bt.glob("predictions_*.csv")):
        d = pd.read_csv(f)
        d = d[d["site"].isin(["fort_simpson", "albany"])]
        rows += d[["site", "site_label", "year", "risk_level", "confidence", "main_scoring"]].to_dict("records")
    R["blind"] = rows
    blind = load_js("blind.js", "blind")
    R["blind_locks"] = blind["locks"]
    R["blind_rules"] = blind["rules"]
    return R, ctrl, W


def chart_controls(ctrl, thr):
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200)
    for y, col, lab in [(2022, RED, "2022: flood year"), (2023, NAVY, "2023: normal year")]:
        s = ctrl[y]
        x = np.arange(len(s)) + (0.15 if y == 2023 else -0.15)
        ax.scatter(np.full(len(s), 0 if y == 2022 else 1) + np.random.default_rng(1).uniform(-0.12, 0.12, len(s)),
                   s["jam_zone_pct_rubble"], s=150, color=col, edgecolor="white", linewidth=1.5, zorder=3)
    ax.axhline(thr, color="#5d6b79", linestyle=(0, (6, 4)), linewidth=2)
    ax.text(1.45, thr + 1.5, f"Jam threshold {thr:.1f}%", ha="right", va="bottom", fontsize=14, color="#5d6b79")
    ax.set_xticks([0, 1], ["2022\nflood year", "2023\nnormal year"], fontsize=16, fontweight="bold")
    ax.set_xlim(-0.5, 1.5)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Jammed (rubble) ice near town, %", fontsize=14)
    ax.tick_params(axis="y", labelsize=13)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color="#dfe3e8", zorder=0)
    fig.tight_layout()
    fig.savefig(OUT / "chart_rcm_controls.png", transparent=True)
    plt.close(fig)


def chart_leadtime(W, R):
    days = [d for d in W["years"]["2022"]["days"] if "03-01" <= d["d"] <= "05-12"]
    col = {"Safe": SAFE, "Possible": POSSIBLE, "High danger": DANGER}
    fig, ax = plt.subplots(figsize=(11, 2.6), dpi=200)
    for i, d in enumerate(days):
        st = "Safe" if d.get("over") else (d.get("status") or "None")
        ax.add_patch(plt.Rectangle((i, 0), 1, 1, color=col.get(st, NONE), linewidth=0))
    idx = {d["d"]: i for i, d in enumerate(days)}
    marks = [(R["replay_2022"]["first_warning"][5:], "First warning\nMar 8"),
             (R["replay_2022"]["first_high_danger"][5:], "High danger\nApr 20"),
             ("05-12", "Peak: town floods\nMay 12")]
    for md, label in marks:
        x = idx[md] + 0.5
        ax.plot([x, x], [1.0, 1.35], color=DEEP, linewidth=2)
        ax.text(x, 1.42, label, ha="center", va="bottom", fontsize=15, color=DEEP, fontweight="bold")
    ax.set_xlim(0, len(days))
    ax.set_ylim(0, 2.25)
    ax.axis("off")
    ax.text(0, -0.28, "Mar 1", fontsize=13, color="#5d6b79", va="top")
    ax.text(len(days), -0.28, "May 12", fontsize=13, color="#5d6b79", va="top", ha="right")
    fig.tight_layout()
    fig.savefig(OUT / "chart_leadtime_2022.png", transparent=True)
    plt.close(fig)


def shot(url, path, w, h, wait=9000):
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    f"--virtual-time-budget={wait}", "--allow-file-access-from-files", f"--window-size={w},{h}",
                    f"--screenshot={path}", url], capture_output=True, timeout=180)
    return Image.open(path)


def crop(img, box, path):
    img.crop(tuple(v * 2 for v in box)).save(path, optimize=True)


def screenshots():
    base = (WEB.as_uri() + "/")
    tmp = OUT / "_full.png"
    im = shot(base + "how-it-works.html", tmp, 1440, 900)
    crop(im, (150, 220, 1290, 721), OUT / "shot_compare.png")
    crop(im, (205, 262, 705, 676), OUT / "shot_flood2022.png")
    im = shot(base + "index.html#2022-05-08", tmp, 1440, 900)
    im.save(OUT / "shot_explorer.png", optimize=True)
    im = shot(base + "index.html#2022-05-08/hay/57,-100,4", tmp, 1440, 900)
    im.save(OUT / "shot_canada.png", optimize=True)
    im = shot(base + "watch.html#2022-05-08", tmp, 1440, 2100)
    # "Places that may be affected" card (map + list), found by its position in the user view.
    crop(im, (150, 1123, 1290, 1662), OUT / "shot_places.png")
    tmp.unlink()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    get_fonts()
    R, ctrl, W = results()
    (OUT / "results.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in R.items() if k not in ("blind", "blind_locks", "blind_rules")}, indent=1))
    chart_controls(ctrl, R["rcm_threshold"])
    chart_leadtime(W, R)
    screenshots()
    print("Saved", sorted(p.name for p in OUT.glob("*.png")))
