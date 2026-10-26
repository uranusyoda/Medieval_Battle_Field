# -*- coding: utf-8 -*-
"""把 tools/anim_sheet.py 渲出的逐帧图拼成一张动作总表。

  python3 tools/make_anim_sheet.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANIM_DIR = os.path.join(ROOT, "assets", "renders", "anim")
OUT = os.path.join(ROOT, "assets", "renders", "templar_anim_sheet.png")

ROWS = {
    "walk": list(range(0, 24, 3)),
    "run": list(range(0, 16, 2)),
    "jump": [0, 4, 8, 12, 16, 20, 26, 32],
    "crouch": list(range(0, 32, 4)),
}
CELL = (420, 540)
LABEL_H = 26


def font(size):
    for path in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def main():
    cols = max(len(v) for v in ROWS.values())
    w = CELL[0] * cols
    h = (CELL[1] + LABEL_H) * len(ROWS)
    sheet = Image.new("RGB", (w, h), (34, 34, 34))
    draw = ImageDraw.Draw(sheet)
    f = font(20)

    for r, (name, frames) in enumerate(ROWS.items()):
        y = r * (CELL[1] + LABEL_H)
        draw.text((10, y + 5), name.upper(), fill=(230, 230, 230), font=f)
        for c, frame in enumerate(frames):
            path = os.path.join(ANIM_DIR, f"{name}_{frame:02d}.png")
            if not os.path.exists(path):
                continue
            im = Image.open(path).convert("RGB")
            sheet.paste(im, (c * CELL[0], y + LABEL_H))
    sheet.save(OUT)
    print(f"{OUT} {sheet.size[0]}x{sheet.size[1]}")


main()
