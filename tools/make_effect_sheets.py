# -*- coding: utf-8 -*-
"""把 2D 效果图拼成对照版 / 装备素材板，并生成 manifest。

输入：assets/concept/hd_effect/final/*.png, gear/*.jpg
输出：
  assets/concept/hd_effect/templar_tpose_compare.png
  assets/concept/hd_effect/templar_gear_sheet.png
  assets/concept/hd_effect/manifest.json
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "concept", "hd_effect")
FINAL = os.path.join(OUT, "final")
GEAR = os.path.join(OUT, "gear")

CN_FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
EN_FONT = "/System/Library/Fonts/Helvetica.ttc"

BG = (18, 18, 20)
PANEL = (27, 27, 30)
TEXT = (236, 231, 221)
MUTED = (150, 146, 138)
ACCENT = (158, 43, 37)


def cn(size):
    return ImageFont.truetype(CN_FONT, size)


def en(size, bold=False):
    return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
                              else "/System/Library/Fonts/Helvetica.ttc", size)


def cover(im, box_w, box_h):
    """等比缩放后居中裁切，填满格子。"""
    w, h = im.size
    s = max(box_w / w, box_h / h)
    im = im.resize((int(w * s + 0.5), int(h * s + 0.5)), Image.LANCZOS)
    w, h = im.size
    left = (w - box_w) // 2
    top = (h - box_h) // 2
    return im.crop((left, top, left + box_w, top + box_h))


def fit(im, box_w, box_h):
    w, h = im.size
    s = min(box_w / w, box_h / h)
    return im.resize((int(w * s + 0.5), int(h * s + 0.5)), Image.LANCZOS)


def header(draw, title, subtitle, width):
    draw.text((70, 58), title, font=cn(74), fill=TEXT)
    draw.text((74, 160), subtitle, font=en(26, True), fill=MUTED)
    draw.rectangle((70, 212, 70 + 120, 216), fill=ACCENT)


def tpose_sheet():
    items = [
        ("01_templar_tpose_unarmored.png", "01  无甲", "UNARMORED", "亚麻内袍 · 布腰带 · 羊毛裤 · 皮靴"),
        ("02_templar_tpose_armored.png", "02  有甲", "ARMORED", "大桶盔 · 锁子甲 · 红十字罩袍 · 披风 · 佩剑"),
    ]
    W, H = 2360, 1980
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    header(d, "圣殿骑士 · T-POSE 对照", "TEMPLAR KNIGHT  ·  T-POSE  ·  HD EFFECT SHEETS", W)

    panel_w, panel_h = 1040, 1390
    gap = 60
    x0 = (W - panel_w * 2 - gap) // 2
    y0 = 270
    for i, (fn, zh, eng, note) in enumerate(items):
        x = x0 + i * (panel_w + gap)
        d.rounded_rectangle((x - 16, y0 - 16, x + panel_w + 16, y0 + panel_h + 16), 10, fill=PANEL)
        im = Image.open(os.path.join(FINAL, fn)).convert("RGB")
        canvas.paste(fit(im, panel_w, panel_h), (x, y0))
        d.text((x, y0 + panel_h + 30), zh, font=cn(42), fill=TEXT)
        d.text((x + 168, y0 + panel_h + 44), eng, font=en(26, True), fill=MUTED)
        d.text((x, y0 + panel_h + 92), note, font=cn(26), fill=MUTED)
        d.text((x, y0 + panel_h + 132), f"{im.size[0]} × {im.size[1]} px", font=en(20), fill=(110, 106, 100))

    d.text((70, H - 70), "TEMPLAR · T-POSE REFERENCE · 2026-10-26", font=en(22), fill=MUTED)
    d.text((W - 340, H - 70), "圣殿骑士团 3D", font=cn(26), fill=MUTED)
    path = os.path.join(OUT, "templar_tpose_compare.png")
    canvas.save(path, optimize=True)
    print("[SHEET]", path, canvas.size)


def gear_sheet():
    labels = {
        "great_helm": ("大桶盔", "GREAT HELM"),
        "kite_shield": ("鸢形盾", "KITE SHIELD"),
        "arming_sword": ("佩剑", "ARMING SWORD"),
        "mail_hauberk": ("锁子甲", "CHAINMAIL HAUBERK"),
        "leather_boots": ("皮靴", "LEATHER BOOTS"),
        "leather_belt": ("腰带", "LEATHER BELT"),
        "wool_cloak": ("披风", "WOOL CLOAK"),
        "leather_gloves": ("手套", "LEATHER GLOVES"),
        "surcoat": ("罩袍", "SURCOAT"),
    }
    files = sorted(f for f in os.listdir(GEAR) if f.endswith((".jpg", ".png")) and not f.startswith("."))
    W, H = 2520, 3200
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    header(d, "圣殿骑士 · 装备素材", "TEMPLAR GEAR  ·  HD PRODUCT SHOTS", W)

    cols, cell_w, cell_h = 3, 780, 900
    img_box = 740
    gap = 30
    x0 = (W - cols * cell_w - (cols - 1) * gap) // 2
    y0 = 285
    for idx, fn in enumerate(files):
        row, col = divmod(idx, cols)
        key = fn.split("_", 1)[1].rsplit(".", 1)[0]
        zh, eng = labels.get(key, (key, key.upper()))
        x = x0 + col * (cell_w + gap)
        y = y0 + row * (cell_h + gap)
        d.rounded_rectangle((x, y, x + cell_w, y + cell_h - 8), 8, fill=PANEL)
        im = Image.open(os.path.join(GEAR, fn)).convert("RGB")
        canvas.paste(cover(im, img_box, img_box), (x + (cell_w - img_box) // 2, y + 14))
        d.text((x + 24, y + img_box + 30), zh, font=cn(38), fill=TEXT)
        d.text((x + 24, y + img_box + 86), eng, font=en(20, True), fill=MUTED)
        d.text((x + cell_w - 96, y + 22), f"{idx + 1:02d}", font=en(22, True), fill=(90, 88, 84))

    d.text((70, H - 70), "TEMPLAR · GEAR SHEET · 1536 px each · 2026-10-26", font=en(22), fill=MUTED)
    d.text((W - 340, H - 70), "圣殿骑士团 3D", font=cn(26), fill=MUTED)
    path = os.path.join(OUT, "templar_gear_sheet.png")
    canvas.save(path, optimize=True)
    print("[SHEET]", path, canvas.size)


def manifest():
    data = {"project": "圣殿骑士团3D", "generator": "MiniMax image-01",
            "date": "2026-10-26", "character_size": [1536, 2048], "gear_size": [1536, 1536],
            "items": []}
    for folder, prefix in ((FINAL, "character"), (GEAR, "gear")):
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith((".jpg", ".png")):
                continue
            meta_path = os.path.join(folder, fn.rsplit(".", 1)[0] + ".json")
            meta = {}
            if os.path.exists(meta_path):
                meta = json.load(open(meta_path, encoding="utf-8"))
            im = Image.open(os.path.join(folder, fn))
            data["items"].append({"type": prefix, "file": os.path.relpath(os.path.join(folder, fn), ROOT),
                                  "width": im.size[0], "height": im.size[1],
                                  "seed": meta.get("seed")})
    path = os.path.join(OUT, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("[MANIFEST]", path, len(data["items"]), "items")


if __name__ == "__main__":
    tpose_sheet()
    gear_sheet()
    manifest()
