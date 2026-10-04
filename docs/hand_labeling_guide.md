# Hand-labelling flood areas in QGIS

**Goal:** draw shapes around places that were clearly **flooded** and places
that were clearly **dry** on the May 12, 2022 radar image. The model learns
from these examples. About 20 flood shapes and 20 dry shapes is plenty.
Expect 30–60 minutes.

---

## 1. Install QGIS (once)
1. Go to https://qgis.org → **Download** → pick the **Long Term Release (LTR)**
   Windows installer.
2. Run it with the default options.

## 2. Make the labels files (once)
In the project folder, run:
```
venv\Scripts\python.exe scripts\04_make_labels.py
```
This creates the three files you need (already done once for you).

## 3. Open the files in QGIS
1. Start QGIS → **Project ▸ New**.
2. Open File Explorer at `data\labels\qgis\` and **drag these into the QGIS map**,
   in this order:
   1. `flood_20220512_view.tif` — the radar picture
   2. `egs_20220514.gpkg` — NRCan's May 14 shapes
3. From `data\labels\`, drag in **`hand_labels.gpkg`** — your (empty) drawing layer.
4. *Optional but helpful:* in the **Browser** panel (left), expand **XYZ Tiles**
   and double-click **OpenStreetMap**. In the **Layers** panel, drag it to the
   **bottom** of the list. Now you can tick/untick the radar picture to see
   street names underneath.

### Make NRCan's shapes see-through
In the **Layers** panel, right-click **egs_flood** → **Properties** →
**Symbology** → click **Simple Fill** → set **Fill style** to *No Brush*,
**Stroke color** to cyan → **OK**. Now you see outlines only.
In NRCan's layer: `class 1` = normal river/lake, `class 2` = flood on May 14.

## 4. How to read the radar picture

| You see | It probably is |
|---|---|
| **Yellow / olive** | Dry land (fields, forest) |
| **Brown / dark red ribbon** | The river, full of broken ice |
| **Blue / purple patches** | Ground that got **darker** since April — possible standing water |
| **Very dark / navy** | Smooth surface: open water — **or pavement** (runways, big parking lots) |
| **Bright white speckles** | Buildings |
| **Black** | No data (outside the satellite image) |

Use mouse scroll to zoom, hold the scroll wheel (or space bar) and drag to pan.

## 5. Draw shapes
1. Click **hand_labels** in the Layers panel so it's selected.
2. Click the **pencil** icon (*Toggle Editing*) on the toolbar.
3. Click **Add Polygon Feature** (the icon of a green shape with a star,
   or press **Ctrl + .**).
4. **Left-click** around the edge of an area to place corners.
   **Right-click** to finish.
5. A small form pops up:
   - **label**: type **1** for *flooded* or **0** for *dry*
   - **note**: optional, e.g. "Vale Island field" or "runway"
   - Leave **fid** as it is → **OK**
6. Repeat for each shape.
7. **Save often:** with **hand_labels** selected, use **Layer ▸ Save Layer
   Edits** (or the toolbar icon of a pencil with a disk).
   ⚠️ **Ctrl + S saves the QGIS *project*, not your shapes.**
8. When done: click the pencil again to stop editing → **Save**.

Made a mistake? With editing on, use **Ctrl + Z** to undo, or use the
**Select Features** tool to click a shape and press **Delete**.

## 6. What to draw

**Flood (label = 1)** — only where you're confident:
- Blue/purple or very dark patches next to the river or channels, especially
  around **Vale Island and Old Town** (the north end, near the lake) and
  along the riverbanks through town.
- Areas inside or right next to NRCan's red class-2 patches that look the
  same in the radar picture.

**Dry (label = 0)** — just as important. Include a mix of:
- Ordinary land: fields, forest, away from the river.
- Town blocks on higher ground, away from the river.
- **The airport runways and big paved areas.** They look dark like water but
  are dry — these teach the model *not* to be fooled.

**Do NOT draw on:**
- The river channel itself or the lake (NRCan's class 1 already covers
  normal water).
- Places where you're unsure — just skip them.

**Tips:** Small, careful shapes beat big sloppy ones. Spread shapes across the
whole image rather than all in one spot. Keep each shape fully inside one kind
of surface.

## 7. When you're done
1. Make sure your edits are saved (step 5.7), then close QGIS. If asked, you
   can save the project as `data\labels\qgis\labeling.qgz` so it's easy to
   reopen.
2. Run:
   ```
   venv\Scripts\python.exe scripts\04_make_labels.py
   ```
   It should print how many flood and dry shapes it found.
3. Tell Claude — next step is training the model.
