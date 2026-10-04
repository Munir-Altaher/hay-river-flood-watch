"""
Step 11b (pitch): build the 5-minute pitch deck and the speaking script.

Reads the pictures and REAL numbers made by scripts/80_pitch_assets.py
(outputs/pitch_assets/results.json); no number in the deck is typed in by hand
except the cited news / government figures listed on the Sources slide.

Blind test: Fort Simpson and Albany River predictions are LOCKED and NOT scored
(outcomes deliberately not checked), so the deck says "not yet scored".

Output: outputs/Polaris_Lifeline_Pitch.pptx, outputs/Polaris_Lifeline_Script.md

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\80_pitch_assets.py   (first, if results changed)
    venv\\Scripts\\python.exe scripts\\81_build_pitch.py
"""

import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS = PROJECT_DIR / "outputs" / "pitch_assets"
LOGOS = PROJECT_DIR / "app" / "assets" / "logos"
OUT_PPTX = PROJECT_DIR / "outputs" / "Polaris_Lifeline_Pitch.pptx"
OUT_MD = PROJECT_DIR / "outputs" / "Polaris_Lifeline_Script.md"

NAVY, DEEP, LIGHT, RED = "26374A", "0B1A2E", "F5F6F8", "EB2D37"
WHITE, GREY, MUTED, TINT = "FFFFFF", "DFE3E8", "5D6B79", "C9D3DE"
HEAD, BODY = "Lato", "Noto Sans"
WPM = 130
R = json.loads((ASSETS / "results.json").read_text(encoding="utf-8"))


def rgb(h):
    return RGBColor.from_string(h)


# ---------------------------------------------------------------- logos (trim empty margin only)
def logo(src, name, width):
    p = ASSETS / name
    if not p.exists():
        im = Image.open(LOGOS / src).convert("RGBA")
        box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        im = im.crop(box)
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        im.save(p, optimize=True)
    return p


LOGO_WORDS = logo("PolarisWords.png", "logo_words.png", 1400)
LOGO_SIDE = logo("PolarisSidebySide.png", "logo_side.png", 1800)
LOGO_STAR = logo("Polaris.png", "logo_star.png", 600)

# ---------------------------------------------------------------- helpers
prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
SW, SH = 13.333, 7.5
SCRIPT = []          # (slide number, title, speaker, text) for the .md file


def bg(slide, colour):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = rgb(colour)


def box(slide, x, y, w, h, fill=None, line=None, shape=MSO_SHAPE.RECTANGLE, radius=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill:
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(1.25)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    return s


def text(slide, x, y, w, h, runs, size=20, colour=NAVY, font=BODY, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, spacing=1.1):
    """runs: a string, or a list of paragraphs; each paragraph a string or a list of (text, overrides)."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = anchor
    paras = runs if isinstance(runs, list) else [runs]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        for piece in (para if isinstance(para, list) else [(para, {})]):
            t, o = piece if isinstance(piece, tuple) else (piece, {})
            r = p.add_run()
            r.text = t
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.name = o.get("font", font)
            r.font.color.rgb = rgb(o.get("colour", colour))
    return tb


def picture(slide, path, x, y, w=None, h=None, border=None):
    """Place a picture inside the (x, y, w, h) box, keeping its shape, centred."""
    im = Image.open(path)
    ar = im.width / im.height
    if w and h:
        if w / h > ar:
            pw, ph = h * ar, h
        else:
            pw, ph = w, w / ar
        x, y = x + (w - pw) / 2, y + (h - ph) / 2
    elif w:
        pw, ph = w, w / ar
    else:
        pw, ph = h * ar, h
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(pw), Inches(ph))
    if border:
        pic.line.color.rgb = rgb(border)
        pic.line.width = Pt(1)
    return pic


def title(slide, t, dark=False, sub=None):
    text(slide, 0.6, 0.42, 10.6, 0.9, t, size=36, colour=WHITE if dark else NAVY, font=HEAD, bold=True)
    box(slide, 0.65, 1.28, 0.9, 0.07, fill=RED if dark else NAVY)
    if sub:
        text(slide, 0.6, 1.42, 11.5, 0.5, sub, size=18, colour=TINT if dark else MUTED)
    picture(slide, LOGO_STAR, SW - 1.15, 0.38, h=0.62)


def footer(slide, n, dark=False):
    c = "8D9BAB" if dark else "9AA5B1"
    text(slide, 0.6, SH - 0.45, 6, 0.3, "Polaris Lifeline  ·  Team Polaris", size=11, colour=c)
    text(slide, SW - 1.6, SH - 0.45, 1.0, 0.3, str(n), size=11, colour=c, align=PP_ALIGN.RIGHT)


def notes(slide, n, ttl, speaker, script, stage=None):
    body = f"{speaker}\n\n{script}"
    if stage:
        body += f"\n\n[{stage}]"
    slide.notes_slide.notes_text_frame.text = body
    SCRIPT.append((n, ttl, speaker, script, stage))


def stat(slide, x, y, w, big, small, big_colour=WHITE, small_colour=TINT, big_size=46):
    text(slide, x, y, w, 0.85, big, size=big_size, colour=big_colour, font=HEAD, bold=True)
    text(slide, x, y + 0.82, w, 0.8, small, size=16, colour=small_colour)


def chip(slide, x, y, w, h, label, fill=LIGHT, colour=NAVY, size=16, bold=False, line=None):
    s = box(slide, x, y, w, h, fill=fill, line=line, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.18)
    tf = s.text_frame
    tf.margin_left = tf.margin_right = Inches(0.12)
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.size = Pt(size)
    r.font.name = BODY
    r.font.bold = bold
    r.font.color.rgb = rgb(colour)
    return s


def arrow(slide, x, y, w=0.45, colour=NAVY):
    a = box(slide, x, y, w, 0.42, fill=colour, shape=MSO_SHAPE.RIGHT_ARROW)
    return a


# ---------------------------------------------------------------- numbers
wk = R["week_ahead"]
rp = R["replay_2022"]
mae = R["mae_7d"]
dw = R["danger_window"]["04-15"]
blind = R["blind"]
n_blind = len(blind)
thr = R["rcm_threshold"]
r22, r23 = R["rcm_2022"], R["rcm_2023"]

# ---------------------------------------------------------------- photos (Cabin Radio, May 2022; credited)
PHOTOS = ASSETS / "photos"


def cover(src, name, w_in, h_in, focus=(0.5, 0.5), dpi=200):
    """Crop a photo to fill a w x h inch box (like CSS object-fit: cover)."""
    im = Image.open(PHOTOS / src).convert("RGB")
    tw, th = round(w_in * dpi), round(h_in * dpi)
    scale = max(tw / im.width, th / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    left = round((im.width - tw) * focus[0])
    top = round((im.height - th) * focus[1])
    p = ASSETS / name
    im.crop((left, top, left + tw, top + th)).save(p, quality=90)
    return p


def title_background():
    """Full-slide photo with a navy fade from the left, so white title text stays readable."""
    base = Image.open(cover("photo_river_may12.jpg", "_title_photo.jpg", SW, SH, focus=(0.5, 0.6))).convert("RGBA")
    w, h = base.size
    alpha = np.clip(np.linspace(1.0, -0.25, w) * 0.96 + 0.18, 0.30, 0.97)
    a = np.tile((alpha * 255).astype(np.uint8), (h, 1))
    shade = Image.new("RGBA", (w, h), tuple(int(DEEP[i:i + 2], 16) for i in (0, 2, 4)) + (0,))
    shade.putalpha(Image.fromarray(a))
    p = ASSETS / "title_bg.jpg"
    Image.alpha_composite(base, shade).convert("RGB").save(p, quality=90)
    return p


PHOTO_CREDIT = "Photos: Kelsey Gill, Tyler Martel, Zachary Pangborn, via Cabin Radio (May 2022)"

# ================================================================= 1. Title
s = prs.slides.add_slide(BLANK)
bg(s, DEEP)
s.shapes.add_picture(str(title_background()), 0, 0, prs.slide_width, prs.slide_height)
picture(s, LOGO_STAR, 0.75, 1.15, h=1.15)
text(s, 0.7, 2.45, 8.0, 1.3, "Polaris Lifeline", size=66, colour=WHITE, font=HEAD, bold=True)
box(s, 0.78, 3.75, 1.3, 0.09, fill=RED)
text(s, 0.7, 4.0, 7.2, 1.2, "Ice-jam flood early warning from RCM satellite radar", size=28, colour=WHITE)
text(s, 0.7, 5.75, 7.2, 0.5, "Team Polaris  ·  Challenge 3", size=20, colour=WHITE, font=HEAD, bold=True)
text(s, 0.7, 6.2, 7.2, 0.4, "[Speaker names]", size=15, colour=TINT)
text(s, SW - 6.1, SH - 0.42, 5.8, 0.3, "Hay River, May 12 2022. Photo: Zachary Pangborn, via Cabin Radio",
     size=10, colour=TINT, align=PP_ALIGN.RIGHT)
notes(s, 1, "Polaris Lifeline", "Speaker 1",
      "Hi everyone. We're Team Polaris, and this is Polaris Lifeline.")

# ================================================================= 2. Story
s = prs.slides.add_slide(BLANK)
bg(s, DEEP)
# Left: the disaster in photos (one large, two small), edge to edge.
s.shapes.add_picture(str(cover("photo_ice_house.jpg", "_p_ice.jpg", 7.4, 4.55, focus=(0.4, 0.6))),
                     0, 0, Inches(7.4), Inches(4.55))
s.shapes.add_picture(str(cover("photo_street.jpg", "_p_street.jpg", 3.67, 2.9, focus=(0.45, 0.6))),
                     0, Inches(4.6), Inches(3.67), Inches(2.9))
s.shapes.add_picture(str(cover("photo_downtown.jpg", "_p_downtown.jpg", 3.68, 2.9, focus=(0.45, 0.55))),
                     Inches(3.72), Inches(4.6), Inches(3.68), Inches(2.9))
chip(s, 0.2, 3.95, 4.3, 0.45, "Ice blocks reach a house on Miron Drive", fill=DEEP, colour=WHITE, size=12)
# Right: what it cost.
text(s, 7.9, 0.5, 5.2, 1.4, [[("May 2022", {})], [("Hay River, NT", {})]], size=34, colour=WHITE, font=HEAD,
     bold=True, spacing=0.95)
box(s, 7.95, 1.95, 0.9, 0.07, fill=RED)
stat(s, 7.9, 2.25, 2.5, "3,500", "ordered to\nevacuate", big_colour=RED, big_size=40)
stat(s, 10.45, 2.25, 2.6, "~500", "homes, businesses and\nbuildings damaged", big_size=40)
stat(s, 7.9, 4.15, 2.5, "$93.6M", "response and\nrecovery", big_size=40)
stat(s, 10.45, 4.15, 2.6, "Few", "had flood\ninsurance", big_size=40)
text(s, 7.9, 5.95, 5.2, 0.5, "Everyone got out safely.", size=18, colour=WHITE, font=HEAD, bold=True)
text(s, 7.9, 6.85, 5.3, 0.45, PHOTO_CREDIT, size=10, colour="8D9BAB")
notes(s, 2, "May 2022. Hay River, NT.", "Speaker 1",
      "May 2022, Hay River. The spring ice jammed at the mouth of the river, and water backed up into town. "
      "About 3,500 people were ordered to evacuate. Around 500 homes, businesses and community buildings were "
      "damaged. Recovery is estimated at 93.6 million dollars, and only a handful had flood insurance. Everyone "
      "got out safely.")

# ================================================================= 3. It keeps happening + how it's watched today
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "It keeps happening")
cards = [
    ("Recent floods", None),
    ("Why ice jams flood", None),
    ("Hard to reach", None),
]
for i, (h, _) in enumerate(cards):
    x = 0.65 + i * 4.1
    box(s, x, 1.6, 3.85, 2.75, fill=LIGHT, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    text(s, x + 0.25, 1.72, 3.4, 0.45, h, size=17, colour=MUTED, font=HEAD, bold=True)
# Card 1: recurrence
text(s, 0.9, 2.2, 1.3, 0.6, "2021", size=30, colour=NAVY, font=HEAD, bold=True)
text(s, 2.2, 2.3, 2.2, 0.6, "Five NWT\ncommunities†", size=15, colour=NAVY)
text(s, 0.9, 3.3, 1.3, 0.6, "2022", size=30, colour=RED, font=HEAD, bold=True)
text(s, 2.2, 3.43, 2.2, 0.5, "Hay River", size=15, colour=NAVY)
# Card 2: cause, as three short numbered steps
for j, (st, hot) in enumerate([("Spring flow breaks the ice", False), ("Ice jams against lake ice", False),
                               ("Water backs up into town", True)]):
    y = 2.25 + j * 0.66
    box(s, 4.98, y, 0.42, 0.42, fill=RED if hot else NAVY, shape=MSO_SHAPE.OVAL)
    text(s, 4.98, y + 0.02, 0.42, 0.38, str(j + 1), size=14, colour=WHITE, font=HEAD, bold=True,
         align=PP_ALIGN.CENTER)
    text(s, 5.5, y + 0.02, 3.0, 0.42, st, size=15, colour=RED if hot else NAVY, bold=hot)
# Card 3: remoteness
text(s, 9.15, 2.25, 3.35, 2.0, [[("Help comes by road, air or boat.", {})], [("", {"size": 8})],
                               [("Breakup closes ice roads and ferries.", {})]], size=16, colour=NAVY)
# Bottom band: a concrete, sourced example of how breakup is watched today.
box(s, 0.65, 4.6, 12.05, 2.05, fill=NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
text(s, 0.95, 4.72, 11.5, 0.45, "How Hay River's breakup is watched today (spring 2026)", size=17, colour=TINT,
     font=HEAD, bold=True)
today = [("GNWT break-up reports", "Gauges, gauge photos, a town camera\nand satellite images, read by experts"),
         ("Town updates", "Facebook, email alerts\nand an emergency hotline"),
         ("Evacuation notice", "Issued “after emergency management\nofficials observe breakup activity\n"
                               "within Hay River boundaries”")]
for i, (h, b) in enumerate(today):
    x = 0.95 + i * 3.9
    text(s, x, 5.2, 3.7, 0.4, h, size=16, colour=WHITE, font=HEAD, bold=True)
    text(s, x, 5.57, 3.7, 1.0, b, size=12.5, colour=WHITE)
text(s, 0.65, 6.7, 8.6, 0.3, "Sources: GNWT Spring Break-Up Report, May 4 2026; My North Now, May 3 2026.  "
     "† 2021 figure: check pending.", size=10, colour="9AA5B1")
text(s, 8.9, 6.66, 3.8, 0.35, "Tells us now, not days ahead.", size=14, colour=RED, font=HEAD, bold=True,
     align=PP_ALIGN.RIGHT)
footer(s, 3)
notes(s, 3, "It keeps happening", "Speaker 1",
      "And it keeps happening: five communities in 2021, then Hay River. Help has to come by road, air or boat, "
      "and breakup closes the ice roads and ferries. Today, the territory publishes break-up reports from gauges, "
      "cameras and satellite images, and the town issues an evacuation notice once officials see breakup inside "
      "town. That's the river now, not what's coming. [Speaker 2]?",
      stage="Handoff to Speaker 2")

# ================================================================= 4. Problem defined
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "The problem, defined")
chip(s, 0.65, 1.65, 12.05, 0.85,
     "Predict the chance of an ice-jam flood in a remote community before it happens, with RCM at the core.",
     fill=NAVY, colour=WHITE, size=19, bold=True)
text(s, 0.65, 2.75, 6, 0.45, "Objectives", size=20, colour=NAVY, font=HEAD, bold=True)
text(s, 6.85, 2.75, 6, 0.45, "Constraints", size=20, colour=MUTED, font=HEAD, bold=True)
objectives = ["Days of lead time", "Where in town", "Few false alarms\nand misses", "Works in other towns",
              "Clear for responders", "No field equipment"]
constraints = ["RCM is the core", "EODMS + open\ndata only", "Very few past floods", "An image every few\ndays, mixed beams",
               "Hackathon time\nand skills", "No field testing"]
for i, (o, c) in enumerate(zip(objectives, constraints)):
    col, row = i % 2, i // 2
    chip(s, 0.65 + col * 2.95, 3.3 + row * 1.0, 2.8, 0.85, o, fill=LIGHT, size=15, bold=True)
    chip(s, 6.85 + col * 2.95, 3.3 + row * 1.0, 2.8, 0.85, c, fill=WHITE, line=GREY, colour=MUTED, size=15)
footer(s, 4)
notes(s, 4, "The problem, defined", "Speaker 2",
      "Our goal: predict the chance of an ice-jam flood before it happens, with RCM satellite radar at the core. "
      "We set six objectives. Days of warning, not hours. Show where in town is at risk. Few false alarms and "
      "missed floods. Work in other towns. Be clear to responders. And need no equipment in the field. Our "
      "limits: only EODMS and open data, very few past floods to learn from, and a new image only every few days.")

# ================================================================= 5. Solution + users
s = prs.slides.add_slide(BLANK)
bg(s, LIGHT)
title(s, "Polaris Lifeline")
text(s, 0.65, 1.7, 5.4, 1.6, [[("Reads the ice that causes the flood, ", {}), ("before", {"colour": RED}),
                              (" it happens.", {})]], size=28, colour=NAVY, font=HEAD, bold=True)
text(s, 0.65, 3.3, 5.4, 0.5, "Most satellite tools map the flood after.", size=18, colour=MUTED)
text(s, 0.65, 4.05, 5.4, 0.45, "Built for", size=16, colour=MUTED, font=HEAD, bold=True)
for i, u in enumerate(["First responders", "Emergency managers", "Community leaders"]):
    chip(s, 0.65, 4.5 + i * 0.62, 3.6, 0.5, u, fill=WHITE, line=GREY, size=16, bold=True)
text(s, 0.65, 6.45, 5.6, 0.4, "4 approaches weighed: compared after the demo.", size=13,
     colour=MUTED)
picture(s, ASSETS / "shot_places.png", 6.35, 1.7, w=6.4, h=4.9, border=GREY)
text(s, 6.35, 6.62, 6.4, 0.3, "Responder view: places at risk on May 8, 2022, four days before the peak",
     size=11, colour=MUTED, align=PP_ALIGN.CENTER)
footer(s, 5)
notes(s, 5, "Polaris Lifeline", "Speaker 2",
      "Our answer is Polaris Lifeline. Most satellite tools map a flood after it happens. We read the ice that "
      "causes the flood, before it happens. It's built for first responders, emergency managers and community "
      "leaders. We weighed four approaches against these goals, and we'll compare them after the demo. "
      "Here's [Speaker 3] on how it works.", stage="Handoff to Speaker 3")

# ================================================================= 6. How it works
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "How it works")
stages = [("1  RCM radar", "Sees through cloud\nand darkness"),
          ("2  Ice map", "Rules sort the river:\nopen water,\nsmooth ice,\njammed rubble ice"),
          ("3  Risk level", "Statistical model,\n46 past springs\n+ RCM jam check"),
          ("4  Where", "Flood map and\nplaces at risk")]
for i, (h, b) in enumerate(stages):
    x = 0.65 + i * 3.15
    hot = i == 2
    box(s, x, 1.85, 2.65, 2.6, fill=NAVY if hot else LIGHT, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    text(s, x + 0.2, 2.0, 2.3, 0.5, h, size=20, colour=WHITE if hot else NAVY, font=HEAD, bold=True)
    text(s, x + 0.2, 2.6, 2.3, 1.7, b, size=15, colour=WHITE if hot else NAVY)
    if i < 3:
        arrow(s, x + 2.7, 2.95, w=0.4)
# What feeds step 3 and the honest description of the ML.
chip(s, 6.95, 4.7, 2.65, 0.8, "River flow, lake level,\nice thickness", fill=WHITE, line=GREY, colour=MUTED, size=13)
box(s, 8.25, 4.48, 0.03, 0.22, fill=GREY)
text(s, 0.65, 5.7, 12.1, 0.5, [[("Jammed ice is bright on radar, open water dark. ", {"bold": True}),
                             ("If radar shows a jam forming, risk goes up a level.", {})]],
     size=17, colour=NAVY)
text(s, 0.65, 6.3, 12, 0.5, f"Ridge regression, each of {R['springs_tested']} springs tested by a model that "
     "never saw it.  Explainable: every number can be traced.", size=13, colour=MUTED)
footer(s, 6)
notes(s, 6, "How it works", "Speaker 3",
      "Two parts. First, the ice. RCM radar sees through cloud and darkness, and jammed ice shows up bright. Our "
      "rules turn each image into a map of open water, smooth ice and jammed ice. Second, a statistical model "
      "trained on 46 past springs forecasts the peak river level. If the radar sees a jam, the risk goes up a level.")

# ================================================================= 7. Flood year vs normal year
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "Flood year vs normal year")
picture(s, ASSETS / "shot_compare.png", 0.65, 1.75, w=7.4, border=GREY)
picture(s, ASSETS / "chart_rcm_controls.png", 8.25, 1.6, w=4.55, h=3.6)
text(s, 8.3, 5.25, 4.5, 1.2, [[(f"2022: {r22['min']:.0f} to {r22['max']:.0f}%", {"colour": RED, "bold": True})],
                             [(f"2023: {r23['min']:.0f} to {r23['max']:.0f}%", {"bold": True})],
                             [(f"Rule: {thr}% sits halfway", {"colour": MUTED})]], size=17, colour=NAVY)
text(s, 0.65, 5.15, 7.4, 0.4, "Amber = jammed ice, red = estimated flooded land. Same place, same season.",
     size=12, colour=MUTED)
footer(s, 7)
notes(s, 7, "Flood year vs normal year", "Speaker 3",
      "We set that rule with a flood year and a normal year: over 90 percent jammed ice in 2022, never above 76 "
      "in 2023. Our line sits halfway.")

# ================================================================= 8. Results
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "Does it work?", sub="Hay River, each spring tested by a model that never saw it")
picture(s, ASSETS / "chart_leadtime_2022.png", 0.65, 1.95, w=12.0, h=2.3)
text(s, 0.65, 4.15, 12, 0.35, "2022 replay: daily risk rating. Grey = no outlook yet, yellow = possible, red = high danger.",
     size=12, colour=MUTED)
cards = [(f"{wk['flood_years_warning_or_higher']} of {wk['flood_years_tested']}", "flood years rated Warning\nor higher a week ahead", RED),
         (f"{wk['normal_springs_warning']} of {wk['normal_springs']}", "normal springs also got\na Warning (false alarms)", NAVY),
         (f"{n_blind} locked", "predictions on 2 new rivers,\nnot yet scored", NAVY)]
for i, (big, small, c) in enumerate(cards):
    x = 0.65 + i * 4.1
    box(s, x, 4.65, 3.8, 1.85, fill=LIGHT, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    text(s, x + 0.25, 4.75, 3.4, 0.8, big, size=36, colour=c, font=HEAD, bold=True)
    text(s, x + 0.25, 5.55, 3.4, 0.9, small, size=15, colour=NAVY)
text(s, 0.65, 6.62, 12, 0.3, f"Peak-level error a week ahead: {mae['model']} m vs {mae['climatology']} m guessing the average "
     f"({R['springs_tested']} springs).", size=11, colour=MUTED)
footer(s, 8)
notes(s, 8, "Does it work?", "Speaker 3",
      "Does it work? Tested on springs it never saw, it rated all five flood years Warning or higher a week ahead. "
      "In 2022, High danger came three weeks early. The trade-off: one in three normal springs also got a Warning. "
      "And twelve predictions on two new rivers are locked, not yet scored. [Speaker 4], show us the tool.",
      stage="Handoff to Speaker 4")

# ================================================================= 9. Live demo
s = prs.slides.add_slide(BLANK)
bg(s, DEEP)
picture(s, LOGO_STAR, SW / 2 - 0.7, 1.2, h=1.4)
text(s, 0, 2.85, SW, 1.0, "Live demo", size=54, colour=WHITE, font=HEAD, bold=True, align=PP_ALIGN.CENTER)
text(s, 0, 3.95, SW, 0.6, "Flood year vs normal year  ·  Responder view  ·  Places at risk", size=20, colour=TINT,
     align=PP_ALIGN.CENTER)
footer(s, 9, dark=True)
notes(s, 9, "Live demo", "Speaker 4",
      "This is our live tool. Hay River at the peak: the 2022 flood year on the left, 2023, a normal year, on the "
      "right. Blue is open water, white is smooth ice, amber is jammed ice, and red is land we estimate flooded. "
      "A few days earlier, 2022 is already jammed solid. 2023 isn't. Afterwards, 2023 clears out. Below is the "
      "prediction: a risk level, a confidence, and one sentence on why. Now the responder view. Pick any day since "
      "2021, and it shows what we would have said that day. May 8, 2022: High danger, breakup any day now. Every "
      "building is coloured by risk, and the side panel lists neighbourhoods, routes and facilities by danger. "
      "Zoom out, and you see every site at once. Back to [Speaker 5].",
      stage="Open web/how-it-works.html (Peak selected) > click Before peak > click After peak > scroll to "
            "Prediction > click 'Back to the map' (index.html) > set day 2022-05-08 > zoom out with the globe button. "
            "If the demo fails, go to the hidden backup slide 9b.")

# ================================================================= 9b. Demo backup (hidden)
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "Demo (backup screenshots)")
picture(s, ASSETS / "shot_compare.png", 0.65, 1.65, w=6.0, h=4.9, border=GREY)
picture(s, ASSETS / "shot_explorer.png", 6.85, 1.65, w=5.85, h=4.9, border=GREY)
text(s, 0.65, 6.6, 6.0, 0.3, "Flood year vs normal year at the peak", size=12, colour=MUTED, align=PP_ALIGN.CENTER)
text(s, 6.85, 6.6, 5.85, 0.3, "Responder view, May 8 2022: High danger", size=12, colour=MUTED, align=PP_ALIGN.CENTER)
s._element.set("show", "0")            # hidden: only shown if the presenter jumps to it
notes(s, "9b", "Demo backup (hidden)", "Speaker 4",
      "Same words as slide 9, pointing at the screenshots: flood year on the left of the first picture, normal "
      "year on the right; the responder view on the right picture.")

# ================================================================= 10. Decision matrix
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "Did we solve it?")
cols = ["", "Lead time", "Where", "Reliable", "Transfers", "Clear", "No field\nkit", "Uses RCM"]
MET, PART, NO, PEND = ("✓", NAVY, WHITE), ("◐", TINT, NAVY), ("✕", LIGHT, "9AA5B1"), ("…", WHITE, NAVY)
rows = [
    ("Ground water sensors", [NO, PART, PART, NO, MET, NO, NO]),
    ("Satellite flood mapping", [NO, MET, PART, MET, MET, MET, MET]),
    ("Weather + gauge model only", [MET, NO, PART, NO, PART, MET, NO]),
    ("Polaris Lifeline: RCM ice + river forecast", [MET, PART, PART, PEND, PART, MET, MET]),
]
evidence = ["3 weeks\n(2022)", "estimate,\nHay River", f"{wk['flood_years_warning_or_higher']}/{wk['flood_years_tested']} floods,\n"
            f"{wk['normal_springs_warning']}/{wk['normal_springs']} false", "blind test\nlocked", "not yet\nuser-tested",
            "EODMS +\nopen data", "core\ninput"]
tbl = s.shapes.add_table(len(rows) + 1, len(cols), Inches(0.65), Inches(1.65), Inches(12.05), Inches(4.4)).table
tbl.columns[0].width = Inches(3.65)
for j in range(1, len(cols)):
    tbl.columns[j].width = Inches(1.2)
for j, c in enumerate(cols):
    cell = tbl.cell(0, j)
    cell.fill.solid()
    cell.fill.fore_color.rgb = rgb(WHITE)
    cell.text = c
    for p in cell.text_frame.paragraphs:
        p.alignment = PP_ALIGN.CENTER
        for r_ in p.runs:
            r_.font.size, r_.font.bold, r_.font.name = Pt(14), True, HEAD
            r_.font.color.rgb = rgb(MUTED)
for i, (name, vals) in enumerate(rows, start=1):
    ours = i == len(rows)
    cell = tbl.cell(i, 0)
    cell.fill.solid()
    cell.fill.fore_color.rgb = rgb(LIGHT if ours else WHITE)
    cell.text = name
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    for r_ in cell.text_frame.paragraphs[0].runs:
        r_.font.size, r_.font.bold, r_.font.name = Pt(16 if ours else 15), ours, HEAD if ours else BODY
        r_.font.color.rgb = rgb(NAVY)
    for j, (sym, fill, ink) in enumerate(vals, start=1):
        cell = tbl.cell(i, j)
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb(fill)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cell.text_frame
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        r_ = tf.paragraphs[0].add_run()
        r_.text = sym
        r_.font.size, r_.font.bold, r_.font.name = Pt(22), True, BODY
        r_.font.color.rgb = rgb(ink)
        if ours:
            p = tf.add_paragraph()
            p.alignment = PP_ALIGN.CENTER
            r2 = p.add_run()
            r2.text = evidence[j - 1]
            r2.font.size, r2.font.name = Pt(10), BODY
            r2.font.color.rgb = rgb(ink)
text(s, 0.65, 6.2, 12, 0.35, "✓ met    ◐ partly    ✕ not met    … pending.   "
     "Our row: our results. Other rows: our assessment.", size=13, colour=MUTED)
text(s, 0.65, 6.55, 12, 0.35, "We tried RCM flood mapping first: F1 0.16 against NRCan flood polygons, and only after "
     "the flood.", size=12, colour=MUTED)
footer(s, 10)
notes(s, 10, "Did we solve it?", "Speaker 5",
      "Did we meet our goals? Lead time: met, weeks of warning in 2022. Where: partly, our flood map is an "
      "estimate, for Hay River only. Reliability: partly, every tested flood caught, but with false alarms. "
      "Transferability: waiting on the blind test. Clarity: built for responders, not yet tested with them. And no "
      "field equipment. The alternatives: sensors only see water once it rises, flood maps come too late, and a "
      "gauge-only model can't see the ice.")

# ================================================================= 11. Next + close
s = prs.slides.add_slide(BLANK)
bg(s, DEEP)
title(s, "What's next", dark=True)
nxt = ["Process every new RCM pass automatically", "Alerts straight to emergency managers",
       "More rivers, more flood years", "Built with communities and responders"]
for i, t in enumerate(nxt):
    box(s, 0.65, 1.85 + i * 0.85, 0.12, 0.55, fill=RED if i == 0 else TINT)
    text(s, 0.95, 1.85 + i * 0.85, 5.8, 0.6, t, size=20, colour=WHITE, anchor=MSO_ANCHOR.MIDDLE)
text(s, 7.1, 2.0, 5.6, 2.4, [[("The next Hay River gets ", {}), ("days", {"colour": RED}), (" of warning,", {})],
                            [("not hours.", {})]], size=38, colour=WHITE, font=HEAD, bold=True, spacing=1.05)
box(s, 7.1, 5.0, 5.6, 1.5, fill=WHITE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
picture(s, LOGO_SIDE, 7.3, 5.15, w=5.2, h=1.2)
footer(s, 11, dark=True)
notes(s, 11, "What's next", "Speaker 5",
      "Next: process every new RCM pass automatically, send alerts to emergency managers, add more rivers, and "
      "build it with the people who'll use it. So the next Hay River gets days of warning, not hours. Thank you.")

# ================================================================= Backups
def backup(n, ttl, rows_, note):
    s = prs.slides.add_slide(BLANK)
    bg(s, WHITE)
    title(s, ttl)
    text(s, 0.65, 0.05, 4, 0.35, "BACKUP", size=11, colour=RED, font=HEAD, bold=True)
    y = 1.75
    for r_ in rows_:
        big, small = r_ if isinstance(r_, tuple) else (r_, None)
        text(s, 0.65, y, 12.0, 0.5, big, size=20, colour=NAVY, font=HEAD, bold=True)
        if small:
            text(s, 0.65, y + 0.48, 12.0, 0.6, small, size=15, colour=MUTED)
        y += 1.05 if small else 0.62
    footer(s, n)
    s.notes_slide.notes_text_frame.text = note
    return s


s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "Sources")
src = [
    "Evacuation (about 3,500 ordered to evacuate): Global News, May 16 2022. "
    "globalnews.ca/news/8838332/hay-river-residents-return-flooding",
    "Damage (~500 homes, businesses, community infrastructure), $93.6M cost, few insured: CKLB Radio, Oct 3 2025. "
    "cklbradio.com/2025/10/03/spring-2022-flood-aftermath-in-hay-river-like-wild-west-says-premier-r-j-simpson",
    "No loss of life: NWT Hansard, May 26 2022 (R. Simpson). hansard.opennwt.ca/debates/2022/5/26/rocky-simpson-1/only",
    "† 2021 flooding (five NWT communities): GNWT newsroom. gov.nt.ca/en/newsroom/shane-thompson-northwest-"
    "territories-community-flood-response-0  (not yet checked: kept closed until the blind test is scored)",
    "Photos (slides 1-2): Kelsey Gill, Tyler Martel, Zachary Pangborn, in \"In pictures: The flood and the people "
    "who faced it\", Cabin Radio, May 13 2022. cabinradio.ca/92792 (copyright the photographers)",
    "How breakup is watched today: GNWT ECC, NWT Water Monitoring Spring Break-Up Report, May 4 2026 "
    "(gov.nt.ca/ecc); \"Hay River monitoring spring break-up as emergency preparedness launches\", My North Now, "
    "May 3 2026. mynorthnow.com/87787",
    "Peak levels and flood years: GNWT (2025) Hay River flood hazard summary report, Table 16. River data: Water "
    "Survey of Canada (HYDAT; 2025-26 provisional). Climate: Environment and Climate Change Canada.",
    "Elevation: NRCan HRDEM lidar (2020), MRDEM. Buildings and roads: © OpenStreetMap contributors. Flood "
    "polygons for checking: NRCan Emergency Geomatics Service. Basemaps: Esri.",
    "Contains RADARSAT Constellation Mission data © Government of Canada (2021-2026). RADARSAT is an official "
    "mark of the Canadian Space Agency.",
]
text(s, 0.65, 1.65, 12.0, 5.3, [[(t, {})] for t in src], size=13, colour=NAVY, spacing=1.25)
footer(s, 12)
s.notes_slide.notes_text_frame.text = "Backup slide: not presented."

backup(13, "Why RCM, not Sentinel-1?", [
    ("RCM is the challenge requirement, and it was built for Canada", "Three satellites watching Canada's North; we "
     "used 16 m images with two polarizations (HH + HV)."),
    ("Same physics, other sensors later", "The ice rules read radar brightness, so Sentinel-1 could fill gaps between "
     "RCM passes as future work."),
    ("Images every few days, in mixed beams", "We correct for viewing angle so different beams can be compared."),
], "Backup for: Why RCM instead of Sentinel-1?")

backup(14, "How accurate is it?", [
    (f"{wk['flood_years_warning_or_higher']} of {wk['flood_years_tested']} flood years: Warning or higher a week ahead",
     f"1985, 1992, 2003, 2008 at Warning; 2022 at Critical. Each tested by a model that never saw that year."),
    (f"{wk['normal_springs_warning']} of {wk['normal_springs']} normal springs also got a Warning, none Critical",
     "Cautious on purpose: missing a flood costs more than a false alarm. 2021 reached High danger with no flood."),
    (f"Peak-level error a week ahead: {mae['model']} m", f"vs {mae['upstream']} m from upstream flow alone and "
     f"{mae['climatology']} m guessing the average ({R['springs_tested']} springs)."),
    (f"Breakup window: real peak inside it in {dw['inside']} of {dw['years']} springs", "Window issued on April 15."),
], "Backup for: How accurate is it really?")

backup(15, "No RCM image this week?", [
    ("The forecast still runs every day", "River flow, lake level and ice thickness keep updating."),
    ("Confidence drops instead", "High needs an RCM image from the last 3 days; otherwise Medium."),
    ("How responders get it today", "A web map: pick a day, see risk, places and routes. Next: automatic alerts."),
], "Backup for: What happens when RCM has no image that week? How would a responder receive this?")

s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "Blind test: locked, not yet scored")
text(s, 0.65, 0.05, 4, 0.35, "BACKUP", size=11, colour=RED, font=HEAD, bold=True)
sites = {"fort_simpson": "Fort Simpson, NT", "albany": "Albany River, ON"}
years = sorted({int(b["year"]) for b in blind})
tbl = s.shapes.add_table(3, len(years) + 1, Inches(0.65), Inches(1.75), Inches(12.05), Inches(2.0)).table
tbl.columns[0].width = Inches(2.75)
for j in range(1, len(years) + 1):
    tbl.columns[j].width = Inches(1.55)
hdr = [""] + [str(y) for y in years]
for j, h in enumerate(hdr):
    c = tbl.cell(0, j)
    c.text = h
    c.fill.solid()
    c.fill.fore_color.rgb = rgb(WHITE)
    for r_ in c.text_frame.paragraphs[0].runs:
        r_.font.size, r_.font.bold, r_.font.name = Pt(15), True, HEAD
        r_.font.color.rgb = rgb(MUTED)
for i, (sid, label) in enumerate(sites.items(), start=1):
    c = tbl.cell(i, 0)
    c.text = label
    c.vertical_anchor = MSO_ANCHOR.MIDDLE
    c.fill.solid()
    c.fill.fore_color.rgb = rgb(LIGHT)
    for r_ in c.text_frame.paragraphs[0].runs:
        r_.font.size, r_.font.bold, r_.font.name = Pt(15), True, HEAD
        r_.font.color.rgb = rgb(NAVY)
    for j, y in enumerate(years, start=1):
        b = next((x for x in blind if x["site"] == sid and int(x["year"]) == y), None)
        c = tbl.cell(i, j)
        c.fill.solid()
        hot = b and b["risk_level"] == "Critical"
        c.fill.fore_color.rgb = rgb(RED if hot else WHITE)
        c.text = (b["risk_level"] + ("*" if not b["main_scoring"] else "")) if b else "-"
        for r_ in c.text_frame.paragraphs[0].runs:
            r_.font.size, r_.font.bold, r_.font.name = Pt(15), True, BODY
            r_.font.color.rgb = rgb(WHITE if hot else NAVY)
        c.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        c.vertical_anchor = MSO_ANCHOR.MIDDLE
lk = R["blind_locks"]
text(s, 0.65, 4.0, 12, 2.6, [
    [("Same Hay River RCM rules, no retraining, RCM images and air temperature only. Outcomes not looked up.", {})],
    [(f"Rules locked {R['blind_rules']['utc']}  SHA-256 {R['blind_rules']['sha256'][:16]}…", {"colour": MUTED})],
] + [[(f"{l['file']}  SHA-256 {l['sha256'][:16]}…", {"colour": MUTED})] for l in lk] + [
    [("* Albany 2025-26: 100 m images only, scored separately. Confidence: Low to Very low (wider rivers, "
      "different beams, tidal estuary).", {"colour": MUTED})],
    [("Hits and misses: [PLACEHOLDER: fill in after scoring]", {"colour": RED, "bold": True})],
], size=14, colour=NAVY, spacing=1.2)
footer(s, 16)
s.notes_slide.notes_text_frame.text = "Backup for: What were the blind test results / misses?"

try:
    prs.save(OUT_PPTX)
except PermissionError:            # the deck is open in PowerPoint: save next to it instead
    OUT_PPTX = OUT_PPTX.with_name(OUT_PPTX.stem + "_new.pptx")
    prs.save(OUT_PPTX)
    print("Main deck is open in PowerPoint, so this version was saved separately.")
print("Saved", OUT_PPTX)

# ================================================================= script file
def words(t):
    return len(re.findall(r"[A-Za-z0-9$.,%'-]+", re.sub(r"\[[^\]]*\]", "Name", t)))


sections = [("Speaker 1", "Story and problem", [1, 2, 3]), ("Speaker 2", "Problem definition and solution", [4, 5]),
            ("Speaker 3", "How it works and results", [6, 7, 8]), ("Speaker 4", "Live demo", [9]),
            ("Speaker 5", "Reflection and close", [10, 11])]
by_n = {n: (ttl, sp, sc, st) for n, ttl, sp, sc, st in SCRIPT}
md = ["# Polaris Lifeline: 5-minute pitch script", "",
      "Team Polaris · Challenge 3. Five speakers: replace **Speaker 1** to **Speaker 5** with your names.",
      f"Timing is at {WPM} words per minute. The deck is `outputs/Polaris_Lifeline_Pitch.pptx`; each slide's lines "
      "are also in its speaker notes.", "", "## Timing", "", "| Speaker | Section | Slides | Words | Time |",
      "|---|---|---|---|---|"]
total_w = 0
for sp, name, ns in sections:
    w = sum(words(by_n[n][2]) for n in ns)
    total_w += w
    sec = round(w / WPM * 60)
    md.append(f"| {sp} | {name} | {', '.join(map(str, ns))} | {w} | {sec // 60}:{sec % 60:02d} |")
tot = round(total_w / WPM * 60)
md += [f"| **Total** | | | **{total_w}** | **{tot // 60}:{tot % 60:02d}** |", "",
       "The 5:00 assumes Speaker 4 clicks while talking (the demo lines take 1:00). Rehearse the clicks: any pause adds to the total.", ""]
for sp, name, ns in sections:
    md += [f"## {sp}: {name}", ""]
    for n in ns:
        ttl, _, sc, st = by_n[n]
        md += [f"**Slide {n}: {ttl}**", "", sc, ""]
        if st:
            md += [f"*{st}*", ""]
md += ["## Q&A prep", "",
       "**Why RCM instead of Sentinel-1?**  ",
       "RCM is the challenge requirement, and it's Canada's own constellation built for watching the North. We used "
       "16 m images with two polarizations. Our rules read radar brightness, so Sentinel-1 could fill gaps later.", "",
       "**How accurate is it really?**  ",
       f"Tested on springs it never saw: all {wk['flood_years_tested']} flood years were rated Warning or higher a week "
       f"ahead. {wk['normal_springs_warning']} of {wk['normal_springs']} normal springs also got a Warning, none Critical. "
       f"Peak-level error a week out is {mae['model']} m, against {mae['climatology']} m for guessing the average. We "
       "chose to be cautious: a missed flood costs more than a false alarm.", "",
       "**What does RCM add, if the forecast uses river gauges?**  ",
       "RCM shows whether a jam is physically forming near town. In 2022 the river forecast was already at Critical, "
       f"and RCM confirmed it: {r22['min']:.0f} to {r22['max']:.0f} percent jammed ice. At new sites without long gauge "
       "records, like our blind-test rivers, RCM is the only input.", "",
       "**Doesn't the GNWT already look at RCM images?**  ",
       "Yes, and that's a strength for us: its spring break-up reports include RCM and optical satellite images, "
       "gauge readings and camera photos, interpreted by experts. Those reports describe conditions as they are. "
       "Polaris Lifeline reads the RCM images automatically and turns them, with river and weather data, into a "
       "daily flood risk with days of lead time and a list of places at risk.", "",
       "**What happens when RCM has no image that week?**  ",
       "The forecast still updates daily from river flow, lake level and ice thickness. Confidence drops from High "
       "to Medium, because High needs an image from the last three days.", "",
       "**How would a first responder actually receive this?**  ",
       "Today, a web map: pick a day and see the risk level, the confidence, and a list of neighbourhoods, routes and "
       "facilities by danger. Next step: automatic alerts to emergency managers when a new RCM pass raises the risk.", "",
       "**What were the blind-test misses, and why?**  ",
       "We haven't scored it yet, on purpose. The predictions for Fort Simpson and the Albany River were locked "
       "with timestamps and fingerprints before anyone looked at outcomes. We already flagged lower confidence there: "
       "wider rivers, different beams, and a tidal estuary at Albany. [PLACEHOLDER: hits and misses after scoring.]", "",
       "**Is this really machine learning? Why not deep learning?**  ",
       "The forecast is a ridge regression trained on 46 springs, and the ice map uses fixed radar rules. There are "
       "only five flood years on record, so a deep model would just memorise them. We chose a model where every "
       "number can be explained to a responder.", "",
       "**How good is the flood map?**  ",
       "It's an estimate from 2020 lidar elevation and a sloping ice-jam water surface. For 2022 it covers 58 percent "
       "of the flooding mapped from RCM and 77 percent of NRCan's mapped flooding, but it also marks a lot of land "
       "that stayed dry, so we call it an estimate and use it to rank places, not to draw exact lines.", "",
       "## Notes for the team", "",
       "- **Placeholder:** blind-test hits and misses (backup slide 16 and Q&A) until the blind test is scored.",
       "- **Not yet checked:** the 2021 figure (five NWT communities). Its source is kept closed until the blind "
       "test is scored, because it may describe a blind-test site. It's marked † on slide 3.",
       "- **Fonts:** install `outputs/pitch_assets/fonts/` (Lato, Noto Sans) on the presenting laptop, or PowerPoint "
       "will substitute other fonts.",
       "- **Demo:** open `web/how-it-works.html` before you start; the map needs internet for its background tiles.",
       "- Slide 9b (demo screenshots) is hidden: jump to it only if the live demo fails."]
OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
print("Saved", OUT_MD, f"({total_w} words, {tot // 60}:{tot % 60:02d})")
