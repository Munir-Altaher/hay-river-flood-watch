"""
Step 1: Find out which RCM satellite scenes exist over Hay River.

This script only SEARCHES the EODMS catalogue - it downloads nothing.
It prints a table of scenes for three time windows and saves it to
outputs/rcm_search_results.csv so we can pick which scenes to download.

Run it from the project folder with:
    venv\\Scripts\\python.exe scripts\\01_search_rcm.py
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from eodms_rapi import EODMSRAPI

# --- Settings ---------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent

# The box around Hay River we care about (longitude latitude pairs).
STUDY_AREA = ("POLYGON ((-115.95 60.75, -115.60 60.75, -115.60 60.92, "
              "-115.95 60.92, -115.95 60.75))")

# Each search window gets a label so we know why we wanted it.
# Dates are written yyyymmdd_hhmmss.
SEARCH_WINDOWS = [
    ("flood_2022",     "20220501_000000", "20220520_235959"),
    ("reference_2022", "20220801_000000", "20220930_235959"),
    ("spring_2021",    "20210420_000000", "20210531_235959"),
    ("spring_2023",    "20230420_000000", "20230531_235959"),
    ("spring_2024",    "20240420_000000", "20240531_235959"),
]

# Extra details we want EODMS to tell us about each scene.
EXTRA_FIELDS = ["Beam Mnemonic", "Polarization", "Product Type"]

# --- Log in -----------------------------------------------------------------

# Read the username/password from the .env file (never printed).
load_dotenv(PROJECT_DIR / ".env")
username = os.getenv("EODMS_USER")
password = os.getenv("EODMS_PASSWORD")
if not username or not password:
    raise SystemExit("Please fill in EODMS_USER and EODMS_PASSWORD in .env")

rapi = EODMSRAPI(username, password)

# --- Search each time window ------------------------------------------------

all_rows = []
for label, start, end in SEARCH_WINDOWS:
    print(f"\nSearching {label} ({start[:8]} to {end[:8]}) ...")
    rapi.search(
        "RCMImageProducts",
        features=[("intersects", STUDY_AREA)],
        dates=[{"start": start, "end": end}],
        result_fields=EXTRA_FIELDS,
    )
    results = rapi.get_results("brief", show_progress=False) or []

    # An error from EODMS comes back as a one-item list with an 'errors' key.
    if results and "errors" in results[0]:
        print("  EODMS returned an error:", results[0]["errors"])
        continue

    print(f"  found {len(results)} scenes")
    for row in results:
        row["window"] = label
        all_rows.append(row)
    rapi.clear_results()  # start fresh for the next window

# --- Show and save the results ----------------------------------------------

if not all_rows:
    raise SystemExit("\nNo scenes found in any window.")

table = pd.DataFrame(all_rows)
out_file = PROJECT_DIR / "outputs" / "rcm_search_results.csv"
table.to_csv(out_file, index=False)
print(f"\nSaved full table to {out_file}")

# Print a short summary: only the columns that are useful to read.
wanted = ["window", "Acquisition Start Date", "Beam Mnemonic",
          "Polarization", "Product Type", "Record ID"]
shown = [c for c in wanted if c in table.columns]
print("\nColumns available:", list(table.columns))
pd.set_option("display.width", 200)
print(table[shown].sort_values(shown[:2]).to_string(index=False))

# How many scenes per window and beam mode - helps us pick ONE beam mode.
if "Beam Mnemonic" in table.columns:
    print("\nScenes per window and beam mode:")
    print(table.groupby(["Beam Mnemonic", "window"]).size()
          .unstack(fill_value=0).to_string())
