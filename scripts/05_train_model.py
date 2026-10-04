"""
Step 5: Train a random forest to find flooded pixels, test it fairly, and
compare it with the simple threshold method.

What the model learns from
--------------------------
Each pixel is described by a few numbers ("features"):
    HH, HV          radar brightness in both channels (dB)
    HH-HV           the ratio between them (in dB a ratio becomes a difference)
    dHH, dHV        change since the reference scene (April 2021)
    HH_mean, HH_std, HV_std
                    texture: average and spread of brightness in a 9x9 window
                    (water is smooth and uniform; land is rougher)

Examples ("labels"):
    flood  - NRCan class-2 patches + your hand-drawn flood shapes,
             on the May 12 01:13 scene (the one you labelled)
    dry    - NRCan dry area + your hand-drawn dry shapes, same scene
    dry    - random pixels from the 2021 and 2024 spring scenes (no flood
             those years) so the model learns that wet snow and river ice
             are NOT flooding
Normal water (river/lake) is left out: it's water, but not flood. It's
masked out of the final maps instead.

How we test it fairly ("spatial block split")
---------------------------------------------
Neighbouring pixels look almost identical, so testing on pixels right next to
training pixels would be cheating. Instead the map is cut into 1 km squares
and the squares are split into 5 groups. The model is trained 5 times, each
time leaving one group of squares out and testing on it. Every labelled
pixel gets tested exactly once by a model that never saw its square.

Scores (for the "flood" class):
    precision  - of the pixels called flood, how many really were
    recall     - of the real flood pixels, how many were found
    F1         - one number balancing precision and recall (1.0 = perfect)
    IoU        - overlap between predicted and real flood area (1.0 = perfect)
    false alarm rate on spring scenes - share of non-flood spring pixels
                 wrongly called flood (lower is better)

Outputs:
    models/flood_rf.joblib                      the trained model
    outputs/model_metrics.csv                   scores, model vs threshold
    data/processed/flood_maps/<scene>_flood.tif 0 dry, 1 flood, 2 normal water, 255 no data
    outputs/flood_maps/<scene>.png              pictures zoomed on town

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\05_train_model.py
"""

from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform
from scipy.ndimage import uniform_filter
from sklearn.ensemble import RandomForestClassifier

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_DIR / "data" / "processed"
REFERENCE = PROCESSED / "reference_2022" / "20210417_012845_16M17.tif"
LABELLED_SCENE = PROCESSED / "flood_2022" / "20220512_011316_16M7.tif"
LABELS = PROCESSED / "labels" / "training_labels.tif"
LABEL_SOURCE = PROCESSED / "labels" / "label_source.tif"   # 1 = NRCan, 2 = hand-drawn
PERMANENT = PROCESSED / "labels" / "permanent_water.tif"
# Spring scenes from non-flood years, 16M beam only (same detail as the flood scenes).
SPRING_SCENES = sorted((PROCESSED / "spring_2021").glob("*_16M*.tif")) + \
                sorted((PROCESSED / "spring_2024").glob("*_16M*.tif"))

FEATURES = ["HH", "HV", "HH-HV", "dHH", "dHV", "HH_mean", "HH_std", "HV_std"]
TEXTURE_WINDOW = 9
BLOCK_PIXELS = 100          # 100 px x 10 m = 1 km squares for the test split
N_FOLDS = 5
MAX_DRY_SAMPLES = 60_000    # dry pixels drawn from the labelled scene per fold
SPRING_SAMPLES = 20_000     # pixels drawn from each spring scene
RANDOM_SEED = 42

DRY, FLOOD, NORMAL_WATER, NO_DATA = 0, 1, 2, 255
TOWN_BOX = (-115.84, 60.74, -115.72, 60.87)   # west, south, east, north (for pictures)


# --- Features ---------------------------------------------------------------

def local_mean_std(image):
    """Average and spread of each pixel's neighbourhood, ignoring no-data."""
    valid = np.isfinite(image)
    filled = np.where(valid, image, 0).astype(np.float64)
    count = uniform_filter(valid.astype(np.float64), TEXTURE_WINDOW)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = uniform_filter(filled, TEXTURE_WINDOW) / count
        mean_sq = uniform_filter(filled ** 2, TEXTURE_WINDOW) / count
        std = np.sqrt(np.maximum(mean_sq - mean ** 2, 0))
    mean[~valid], std[~valid] = np.nan, np.nan
    return mean.astype(np.float32), std.astype(np.float32)


def scene_features(scene_path, ref_hh, ref_hv):
    """Return an array of shape (rows, cols, n_features) for one scene."""
    with rasterio.open(scene_path) as src:
        hh, hv = src.read(1), src.read(2)
    hh_mean, hh_std = local_mean_std(hh)
    _, hv_std = local_mean_std(hv)
    stack = [hh, hv, hh - hv, hh - ref_hh, hv - ref_hv, hh_mean, hh_std, hv_std]
    return np.stack(stack, axis=-1).astype(np.float32)


# --- Simple threshold baseline (same idea as script 03) ---------------------

def otsu_threshold(values, bins=256):
    hist, edges = np.histogram(values, bins=bins)
    centres = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centres) / np.maximum(w0, 1)
    m1 = ((hist * centres).sum() - np.cumsum(hist * centres)) / np.maximum(w1, 1)
    return float(centres[np.argmax(w0 * w1 * (m0 - m1) ** 2)])


def threshold_flood(hh):
    """Baseline: dark pixels (below the scene's Otsu cut-off) count as flood."""
    cutoff = otsu_threshold(hh[np.isfinite(hh)])
    return (hh < cutoff).astype(np.uint8)


# --- Scoring ----------------------------------------------------------------

def scores(truth, pred):
    tp = int(((pred == 1) & (truth == 1)).sum())
    fp = int(((pred == 1) & (truth == 0)).sum())
    fn = int(((pred == 0) & (truth == 1)).sum())
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    iou = tp / max(tp + fp + fn, 1)
    return dict(precision=round(precision, 3), recall=round(recall, 3),
                F1=round(f1, 3), IoU=round(iou, 3))


def make_model():
    return RandomForestClassifier(n_estimators=200, min_samples_leaf=5,
                                  class_weight="balanced_subsample",
                                  n_jobs=-1, random_state=RANDOM_SEED)


# --- Picture ----------------------------------------------------------------

def save_picture(path, hh, flood_map, title, grid):
    xs, ys = transform("EPSG:4326", grid.crs, TOWN_BOX[::2], TOWN_BOX[1::2])
    (r0, c0), (r1, c1) = grid.index(xs[0], ys[1]), grid.index(xs[1], ys[0])
    fig, axes = plt.subplots(1, 2, figsize=(16, 9))
    axes[0].imshow(hh[r0:r1, c0:c1], cmap="gray", vmin=-25, vmax=0)
    axes[0].set_title("Radar HH")
    axes[1].imshow(hh[r0:r1, c0:c1], cmap="gray", vmin=-25, vmax=0)
    shown = flood_map[r0:r1, c0:c1].astype(float)
    shown[(shown == DRY) | (shown == NO_DATA)] = np.nan
    axes[1].imshow(shown, cmap=ListedColormap(["red", "deepskyblue"]), vmin=1, vmax=2,
                   alpha=0.7, interpolation="nearest")
    axes[1].set_title("Model: red = flood, blue = normal water")
    for ax in axes:
        ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle(title, fontsize=14)
    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(path, dpi=80)
    plt.close(fig)


# --- Main -------------------------------------------------------------------

if __name__ == "__main__":
    rng = np.random.default_rng(RANDOM_SEED)
    grid = rasterio.open(REFERENCE)
    ref_hh, ref_hv = grid.read(1), grid.read(2)
    labels = rasterio.open(LABELS).read(1)
    permanent = rasterio.open(PERMANENT).read(1) == 1

    # Which 1 km square each pixel is in, and which test group that square is in.
    rows, cols = np.indices(grid.shape)
    block = (rows // BLOCK_PIXELS) * (grid.shape[1] // BLOCK_PIXELS + 1) + cols // BLOCK_PIXELS
    fold_of_block = rng.permutation(block.max() + 1) % N_FOLDS
    fold = fold_of_block[block]

    # --- Gather labelled pixels from the flood scene ------------------------
    print("Computing features for the labelled flood scene ...")
    feats = scene_features(LABELLED_SCENE, ref_hh, ref_hv)
    usable = np.all(np.isfinite(feats), axis=-1)
    lab_mask = usable & ((labels == FLOOD) | (labels == DRY))
    X_scene = feats[lab_mask]
    y_scene = (labels[lab_mask] == FLOOD).astype(np.uint8)
    fold_scene = fold[lab_mask]
    source_scene = rasterio.open(LABEL_SOURCE).read(1)[lab_mask]
    base_scene = threshold_flood(feats[..., 0])[lab_mask]
    print(f"  labelled pixels: {y_scene.sum():,} flood, {(y_scene == 0).sum():,} dry")
    for code, name in [(1, "NRCan"), (2, "hand-drawn")]:
        s = source_scene == code
        print(f"    from {name}: {y_scene[s].sum():,} flood, {(y_scene[s] == 0).sum():,} dry")

    # --- Gather spring (non-flood) pixels -----------------------------------
    X_spring, fold_spring, base_spring, name_spring = [], [], [], []
    for scene in SPRING_SCENES:
        f = scene_features(scene, ref_hh, ref_hv)
        ok = np.all(np.isfinite(f), axis=-1) & ~permanent
        idx = np.flatnonzero(ok)
        pick = rng.choice(idx, size=min(SPRING_SAMPLES, len(idx)), replace=False)
        X_spring.append(f.reshape(-1, len(FEATURES))[pick])
        fold_spring.append(fold.ravel()[pick])
        base_spring.append(threshold_flood(f[..., 0]).ravel()[pick])
        name_spring += [scene.stem] * len(pick)
        print(f"  spring scene {scene.stem}: {len(pick):,} pixels")
    X_spring = np.concatenate(X_spring)
    fold_spring = np.concatenate(fold_spring)
    base_spring = np.concatenate(base_spring)
    name_spring = np.array(name_spring)

    # --- Spatial block cross-validation -------------------------------------
    print(f"\nTesting with {N_FOLDS}-fold spatial block split ...")
    pred_scene = np.zeros_like(y_scene)
    pred_spring = np.zeros(len(X_spring), dtype=np.uint8)
    for k in range(N_FOLDS):
        train_s, test_s = fold_scene != k, fold_scene == k
        flood_idx = np.flatnonzero(train_s & (y_scene == 1))
        dry_idx = np.flatnonzero(train_s & (y_scene == 0))
        dry_idx = rng.choice(dry_idx, size=min(MAX_DRY_SAMPLES, len(dry_idx)), replace=False)
        spring_idx = np.flatnonzero(fold_spring != k)

        X_train = np.concatenate([X_scene[flood_idx], X_scene[dry_idx], X_spring[spring_idx]])
        y_train = np.concatenate([np.ones(len(flood_idx)), np.zeros(len(dry_idx)),
                                  np.zeros(len(spring_idx))]).astype(np.uint8)
        model = make_model().fit(X_train, y_train)
        pred_scene[test_s] = model.predict(X_scene[test_s])
        test_sp = fold_spring == k
        pred_spring[test_sp] = model.predict(X_spring[test_sp])
        print(f"  fold {k + 1}: trained on {len(flood_idx):,} flood / "
              f"{len(dry_idx) + len(spring_idx):,} non-flood pixels")

    rows_out = []
    for method, p_scene, p_spring in [("random forest", pred_scene, pred_spring),
                                      ("threshold (Otsu)", base_scene, base_spring)]:
        r = {"method": method, **scores(y_scene, p_scene),
             "spring_false_alarm_pct": round(100 * p_spring.mean(), 2)}
        for name in np.unique(name_spring):
            r[f"false_alarm_{name}_pct"] = round(100 * p_spring[name_spring == name].mean(), 2)
        rows_out.append(r)
    metrics = pd.DataFrame(rows_out)
    metrics.to_csv(PROJECT_DIR / "outputs" / "model_metrics.csv", index=False)
    print("\nResults on held-out 1 km squares (all labels):")
    print(metrics[["method", "precision", "recall", "F1", "IoU",
                   "spring_false_alarm_pct"]].to_string(index=False))

    # The same predictions, scored separately against each label source.
    by_source = []
    for code, name in [(1, "NRCan (May 14)"), (2, "hand-drawn (May 12)")]:
        s = source_scene == code
        for method, p in [("random forest", pred_scene), ("threshold (Otsu)", base_scene)]:
            by_source.append({"labels": name, "method": method, **scores(y_scene[s], p[s])})
    by_source = pd.DataFrame(by_source)
    by_source.to_csv(PROJECT_DIR / "outputs" / "model_metrics_by_source.csv", index=False)
    print("\nScored separately by where the labels came from:")
    print(by_source.to_string(index=False))

    # --- Final model on all data --------------------------------------------
    print("\nTraining final model on all labelled data ...")
    flood_idx = np.flatnonzero(y_scene == 1)
    dry_idx = rng.choice(np.flatnonzero(y_scene == 0),
                         size=min(MAX_DRY_SAMPLES, int((y_scene == 0).sum())), replace=False)
    X_all = np.concatenate([X_scene[flood_idx], X_scene[dry_idx], X_spring])
    y_all = np.concatenate([np.ones(len(flood_idx)), np.zeros(len(dry_idx)),
                            np.zeros(len(X_spring))]).astype(np.uint8)
    model = make_model().fit(X_all, y_all)
    (PROJECT_DIR / "models").mkdir(exist_ok=True)
    joblib.dump({"model": model, "features": FEATURES}, PROJECT_DIR / "models" / "flood_rf.joblib")

    print("Which features the model relied on most:")
    for name, imp in sorted(zip(FEATURES, model.feature_importances_), key=lambda t: -t[1]):
        print(f"  {name:8s} {imp:.2f}")

    # --- Flood maps for every flood scene -----------------------------------
    print("\nMapping every flood scene ...")
    out_dir = PROCESSED / "flood_maps"
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = grid.profile.copy()
    profile.update(count=1, dtype="uint8", nodata=NO_DATA, compress="deflate")
    for scene in sorted((PROCESSED / "flood_2022").glob("*.tif")):
        f = scene_features(scene, ref_hh, ref_hv)
        ok = np.all(np.isfinite(f), axis=-1)
        flood_map = np.full(grid.shape, NO_DATA, dtype=np.uint8)
        flood_map[ok] = model.predict(f[ok])
        flood_map[ok & permanent] = NORMAL_WATER
        with rasterio.open(out_dir / f"{scene.stem}_flood.tif", "w", **profile) as dst:
            dst.write(flood_map, 1)
        km2 = (flood_map == FLOOD).sum() * 100 / 1e6
        print(f"  {scene.stem}: {km2:.2f} km2 flagged as flood "
              f"({100 * ok.mean():.0f}% of study area visible)")
        save_picture(PROJECT_DIR / "outputs" / "flood_maps" / f"{scene.stem}.png",
                     f[..., 0], flood_map, f"Hay River - {scene.stem}", grid)

    print("\nDone. Scores: outputs/model_metrics.csv, pictures: outputs/flood_maps/")
