"""
Blind test, step 1: order and download RCM scenes for a blind-test site.

Sites and image choice (approved by the user):
  fort_simpson  16M beams (same as the Hay River training images), GRD, HH+HV,
                every scene covering Fort Simpson, springs 2021-2026
  albany        30 m ScanSAR (SC30M*) beams, GRD, HH+HV, springs 2021-2024, plus
                100 m ScanSAR (SCLN*) for 2025 and 2026 (reported separately, low confidence)

Scenes come from outputs/blind_test/catalogue.csv (a catalogue SEARCH made during
planning). If a site/year has many scenes, at most MAX_PER_YEAR are taken, spread
evenly through the season so before, during and after breakup are all covered.

Usage (from the project folder):
    venv\\Scripts\\python.exe scripts\\70_blind_order.py <site> list
    venv\\Scripts\\python.exe scripts\\70_blind_order.py <site> order
    venv\\Scripts\\python.exe scripts\\70_blind_order.py <site> download
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from eodms_rapi import EODMSRAPI

PROJECT_DIR = Path(__file__).resolve().parent.parent
CATALOGUE = PROJECT_DIR / "outputs" / "blind_test" / "catalogue.csv"
CHUNK = 50
MAX_PER_YEAR = {"fort_simpson": 30, "albany": 14}
CHECK_EVERY_S, MAX_CHECKS = 60, 120


def dest(site):
    return PROJECT_DIR / "data" / "rcm" / "blind" / site


def choose(site):
    c = pd.read_csv(CATALOGUE, parse_dates=["date_utc"])
    c = c[(c["site"] == site) & (c["type"] == "GRD") & (c["pol"] == "HH HV") & c["towns_covered"].notna()]
    if site == "fort_simpson":
        c = c[c["beam"].str.startswith("16M")]
    else:
        # 2021-2024: 30 m ScanSAR. 2025 has only ONE 30 m scene over the communities and
        # 2026 has none, so both use 100 m ScanSAR (reported separately, low confidence).
        c = c[((c["year"] <= 2024) & c["beam"].str.startswith("SC30M")) |
              ((c["year"] >= 2025) & c["beam"].str.startswith("SCLN"))]
    c = c.sort_values("corridor_cover_pct", ascending=False).drop_duplicates("record_id")
    picked = []
    for year, g in c.groupby("year"):
        # One scene per day (best coverage), then spread evenly over the season.
        g = g.assign(day=g["date_utc"].dt.date).sort_values("corridor_cover_pct", ascending=False) \
             .drop_duplicates("day").sort_values("date_utc")
        n = MAX_PER_YEAR[site]
        if len(g) > n:
            g = g.iloc[np.unique(np.linspace(0, len(g) - 1, n).round().astype(int))]
        picked.append(g)
    out = pd.concat(picked)
    have = {p.stem for p in dest(site).glob("*.zip")} | set(_processed(site))
    return out[~out["title"].isin(have)]


def _processed(site):
    folder = PROJECT_DIR / "data" / "processed" / "blind" / site / "scenes"
    return [t.stem for t in folder.glob("*.tif")] if folder.exists() else []


def login():
    load_dotenv(PROJECT_DIR / ".env")
    return EODMSRAPI(os.getenv("EODMS_USER"), os.getenv("EODMS_PASSWORD"))


if __name__ == "__main__":
    site, step = sys.argv[1], sys.argv[2]
    d = dest(site)
    d.mkdir(parents=True, exist_ok=True)
    orders = d / "orders.json"
    if step == "list":
        s = choose(site)
        print(f"{site}: {len(s)} scenes to order")
        print(s.groupby("year").agg(scenes=("title", "size"), first=("date_utc", "min"), last=("date_utc", "max"),
                                    beams=("beam", lambda b: " ".join(sorted(set(b))))).to_string())
    elif step == "order":
        if orders.exists():
            raise SystemExit(f"Already ordered ({orders}); use 'download'.")
        s = choose(site)
        rapi = login()
        recs = [{"collectionId": "RCMImageProducts", "recordId": str(r)} for r in s["record_id"]]
        items = []
        for i in range(0, len(recs), CHUNK):
            res = rapi.order(recs[i:i + CHUNK])
            if not res or "items" not in res:
                raise SystemExit(f"EODMS did not accept the order: {res}")
            items += res["items"]
            print(f"  part {i // CHUNK + 1}: {len(res['items'])} scenes submitted")
        orders.write_text(json.dumps([{k: it.get(k) for k in ("orderId", "itemId", "recordId", "collectionId")}
                                      for it in items], indent=1))
        s.to_csv(d / "ordered_scenes.csv", index=False)
        print(f"Ordered {len(items)} scenes for {site}")
    elif step == "download":
        items = json.loads(orders.read_text())
        done = set(_processed(site)) | {p.stem for p in d.glob("*.zip")}
        ordered = pd.read_csv(d / "ordered_scenes.csv")
        todo_ids = set(ordered.loc[~ordered["title"].isin(done), "record_id"].astype(str))
        todo = [it for it in items if str(it["recordId"]) in todo_ids]
        print(f"{site}: {len(items)} ordered, {len(items) - len(todo)} already downloaded or processed")
        if todo:
            login().download(todo, str(d), wait=CHECK_EVERY_S, max_attempts=MAX_CHECKS, show_progress=False)
        print(f"zips now in {d}: {len(list(d.glob('*.zip')))}")
