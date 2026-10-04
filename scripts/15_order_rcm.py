"""
Step 1f (new plan): Order and download the RCM scenes chosen from the
catalogue search (script 11).

Which scenes: 16M beam (16 m detail), GRD, HH+HV, that show the river from
the lake up past the town (river km 0-15 visible), springs 2021 onward, and
not already in data/rcm/.

Two steps, run separately:

    venv\\Scripts\\python.exe scripts\\15_order_rcm.py order
        Places the order with EODMS (free public RCM data) using your login
        in .env. Saves the order details to data/rcm/corridor/orders.json.
        Refuses to order again if that file already exists (so you can't
        accidentally order everything twice).

    venv\\Scripts\\python.exe scripts\\15_order_rcm.py download
        Checks the orders and downloads every scene that EODMS has finished
        preparing into data/rcm/corridor/. Preparing can take minutes to
        hours. Safe to run again and again: scenes already downloaded are
        skipped.
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from eodms_rapi import EODMSRAPI

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCENES_CSV = PROJECT_DIR / "outputs" / "rcm_corridor_scenes.csv"
DEST = PROJECT_DIR / "data" / "rcm" / "corridor"
ORDERS_FILE = DEST / "orders.json"

FIRST_YEAR = 2021
MAX_KM_FROM = 15         # scene must see the river at least from km 15 down to the lake
CHUNK = 50               # scenes per order
CHECK_EVERY_S = 60       # how often to check whether orders are ready
MAX_CHECKS = 90          # stop after this many checks (~1.5 h); just run again later


def choose_scenes():
    t = pd.read_csv(SCENES_CSV)
    chosen = t[(t["product_type"] == "GRD") & (t["polarization"] == "HH HV")
               & t["beam"].str.startswith("16M") & (t["year"] >= FIRST_YEAR)
               & (t["km_from"] <= MAX_KM_FROM)]
    have = {p.stem for p in (PROJECT_DIR / "data" / "rcm").rglob("*.zip")}
    chosen = chosen[~chosen["title"].isin(have)].drop_duplicates("record_id")
    return chosen.sort_values("date_utc")


def login():
    load_dotenv(PROJECT_DIR / ".env")
    user, password = os.getenv("EODMS_USER"), os.getenv("EODMS_PASSWORD")
    if not user or not password:
        raise SystemExit("Please fill in EODMS_USER and EODMS_PASSWORD in .env")
    return EODMSRAPI(user, password)


def place_order():
    if ORDERS_FILE.exists():
        raise SystemExit(f"Orders already placed ({ORDERS_FILE}). Run with 'download' instead.")
    scenes = choose_scenes()
    print(f"Ordering {len(scenes)} scenes:")
    print(scenes.groupby("year").size().to_string())
    rapi = login()
    records = [{"collectionId": "RCMImageProducts", "recordId": str(r)} for r in scenes["record_id"]]
    items = []
    for start in range(0, len(records), CHUNK):
        result = rapi.order(records[start:start + CHUNK])
        if not result or "items" not in result:
            raise SystemExit(f"EODMS did not accept the order: {result}")
        items += result["items"]
        print(f"  order part {start // CHUNK + 1}: {len(result['items'])} scenes submitted")
    DEST.mkdir(parents=True, exist_ok=True)
    keep = [{k: it.get(k) for k in ("orderId", "itemId", "recordId", "collectionId", "status")}
            for it in items]
    ORDERS_FILE.write_text(json.dumps(keep, indent=1))
    print(f"Saved order details to {ORDERS_FILE}")
    print("Next: run this script with 'download' (EODMS may take a while to prepare them).")


def download():
    if not ORDERS_FILE.exists():
        raise SystemExit("No orders yet - run with 'order' first.")
    items = json.loads(ORDERS_FILE.read_text())
    have = {p.stem for p in DEST.glob("*.zip")}
    print(f"{len(items)} scenes ordered, {len(have)} already downloaded in {DEST}")
    rapi = login()
    rapi.download(items, str(DEST), wait=CHECK_EVERY_S, max_attempts=MAX_CHECKS,
                  show_progress=False)
    have = sorted(p.name for p in DEST.glob("*.zip"))
    print(f"\nNow {len(have)} of {len(items)} scenes downloaded.")
    if len(have) < len(items):
        print("Some are still being prepared - run 'download' again later.")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step == "order":
        place_order()
    elif step == "download":
        download()
    elif step == "list":
        s = choose_scenes()
        print(f"{len(s)} scenes would be ordered:")
        print(s[["date_utc", "beam", "orbit", "km_from", "km_to"]].to_string(index=False))
    else:
        raise SystemExit("Use: 15_order_rcm.py list | order | download")
