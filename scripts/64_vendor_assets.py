"""
Step 10a (map explorer): save the map library, fonts and logo copies into web/.

  * Leaflet 1.9.4 (map library) -> web/vendor/leaflet/
  * Lato and Noto Sans (SIL Open Font License, free to redistribute) -> web/vendor/fonts/
    plus web/vendor/fonts/fonts.css
  * Logos: copies of app/assets/logos with ONLY the empty transparent margin
    trimmed (artwork not edited, recoloured or redrawn) -> web/assets/
      polaris_side.png   side-by-side logo, for the light panel header
      polaris_star.png   star only, for the dark map and compact spots
      favicon.png        star only, 64 x 64, for the browser tab

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\64_vendor_assets.py
"""

import re
from pathlib import Path

import requests
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parent.parent
WEB = PROJECT_DIR / "web"
LOGOS = PROJECT_DIR / "app" / "assets" / "logos"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")


def get(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    return r


def trim(src, dst, pad_frac=0.04, size=None, width=None):
    im = Image.open(src).convert("RGBA")
    box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    w, h = box[2] - box[0], box[3] - box[1]
    p = int(max(w, h) * pad_frac)
    box = (max(0, box[0] - p), max(0, box[1] - p), min(im.width, box[2] + p), min(im.height, box[3] + p))
    out = im.crop(box)
    if size:
        side = max(out.size)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(out, ((side - out.width) // 2, (side - out.height) // 2))
        out = sq.resize((size, size), Image.LANCZOS)
    elif width:
        out = out.resize((width, round(out.height * width / out.width)), Image.LANCZOS)
    out.save(dst, optimize=True)
    print(f"  {dst.name}: {out.size[0]} x {out.size[1]}")


if __name__ == "__main__":
    lf = WEB / "vendor" / "leaflet"
    lf.mkdir(parents=True, exist_ok=True)
    base = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/"
    for f in ["leaflet.min.js", "leaflet.min.css"]:
        (lf / f).write_bytes(get(base + f).content)
        print(f"  leaflet/{f}")
    # Icons the stylesheet points to (layer switcher, default markers).
    (lf / "images").mkdir(exist_ok=True)
    for f in ["layers.png", "layers-2x.png", "marker-icon.png", "marker-icon-2x.png", "marker-shadow.png"]:
        (lf / "images" / f).write_bytes(get(base + "images/" + f).content)
        print(f"  leaflet/images/{f}")

    fonts = WEB / "vendor" / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    css = get("https://fonts.googleapis.com/css2?family=Lato:wght@400;700&family=Noto+Sans:wght@400;600&display=swap").text
    out_css = []
    # Keep only the "latin" blocks (English and French characters).
    for block in re.findall(r"/\* ([a-z-]+) \*/\s*(@font-face \{.*?\})", css, flags=re.S):
        subset, face = block
        if subset != "latin":
            continue
        fam = re.search(r"font-family: '([^']+)'", face).group(1)
        wt = re.search(r"font-weight: (\d+)", face).group(1)
        url = re.search(r"url\((https://[^)]+)\)", face).group(1)
        name = f"{fam.replace(' ', '')}-{wt}.woff2"
        (fonts / name).write_bytes(get(url).content)
        out_css.append(re.sub(r"url\(https://[^)]+\)", f"url({name})", face))
        print(f"  fonts/{name}")
    (fonts / "fonts.css").write_text("\n".join(out_css) + "\n", encoding="utf-8")

    assets = WEB / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    trim(LOGOS / "PolarisSidebySide.png", assets / "polaris_side.png", width=840)
    trim(LOGOS / "Polaris.png", assets / "polaris_star.png", width=256)
    trim(LOGOS / "PolarisWords.png", assets / "polaris_words.png", width=520)
    trim(LOGOS / "Polaris.png", assets / "favicon.png", size=64)
