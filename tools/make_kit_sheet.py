# -*- coding: utf-8 -*-
"""把「同一角色 × 不同阶层装备」拼成对照版，并写 manifest。

输入：assets/concept/hd_effect/kit/final/*.jpg
输出：
  assets/concept/hd_effect/kit/rank_compare.png
  assets/concept/hd_effect/kit/manifest.json
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "assets", "concept", "hd_effect", "kit")
FINAL = os.path.join(KIT, "final")

CN = "/System/Library/Fonts/STHeiti Medium.ttc"
EN = "/System/Library/Fonts/Helvetica.ttc"
EN_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

BG = (17, 17, 19)
PANEL = (26, 26, 29)
TEXT = (236, 231, 221)
MUTED = (148, 144, 136)
ACCENT = (158, 43, 37)
DIM = (104, 100, 94)


def cn(size):
    return ImageFont.truetype(CN, size)


def en(size, bold=False):
    return ImageFont.truetype(EN_B if bold else EN, size)


def fit(im, bw, bh):
    w, h = im.size
    s = min(bw / w, bh / h)
    return im.resize((int(w * s + 0.5), int(h * s + 0.5)), Image.LANCZOS)


# 四个阶层的文案：与本项目 docs/04_设定/圣殿骑士团建制与装备.md 对应
ITEMS = [
    ("01_knight_tpose.jpg", "01", "骑士兄弟 · 露脸", "KNIGHT BROTHER",
     ["白罩袍 · 胸前单一红十字", "锁甲长袍 + 锁甲头巾 · 锥盔", "羊毛披风 · 皮靴 · 腰剑挂点"]),
    ("02_knight_helmed.jpg", "02", "骑士兄弟 · 闭盔", "KNIGHT · CLOSED HELM",
     ["同上，换闭面盔（眼缝）", "面部不可见，便于做量产单位", "与 3D 大桶盔设定同源"]),
    ("03_sergeant.jpg", "03", "军士兄弟", "SERGEANT BROTHER",
     ["深褐罩袍 + 红十字（非白袍）", "锁甲 + 铁壶盔 · 轻骑一人一马", "长矛 / 弩为副，甲比骑士轻"]),
    ("04_turcopole.jpg", "04", "突厥轻骑", "TURCOPOLE",
     ["无锁甲：厚棉甲 + 软帽", "复合弓 + 箭袋，侦察与袭扰", "不穿白袍、不佩红十字"]),
]


def before_after():
    """无甲 → 全装：同一角色、同一 T-pose 的前后对照。"""
    src = os.path.join(ROOT, "assets", "concept", "input", "templar_tpose_20261026.jpg")
    dst = os.path.join(FINAL, "01_knight_tpose.jpg")
    if not (os.path.exists(src) and os.path.exists(dst)):
        return
    W, H = 2360, 1980
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    d.text((70, 58), "同一角色 · 装备前后", font=cn(74), fill=TEXT)
    d.text((74, 160), "SAME MAN  ·  UNARMORED  →  FULL TEMPLAR KIT", font=en(26, True), fill=MUTED)
    d.rectangle((70, 212, 190, 216), fill=ACCENT)

    pw, ph, gap = 1040, 1390, 60
    x0 = (W - pw * 2 - gap) // 2
    y0 = 270
    for i, (path, zh, eng, note) in enumerate([
            (src, "无甲", "UNARMORED", "亚麻内袍 · 布腰带 · 羊毛裤 · 皮靴"),
            (dst, "全装", "FULL KIT", "锁甲 · 白罩袍单十字 · 锥盔 · 披风 · 腰剑挂点")]):
        x = x0 + i * (pw + gap)
        d.rounded_rectangle((x - 16, y0 - 16, x + pw + 16, y0 + ph + 16), 10, fill=PANEL)
        im = Image.open(path).convert("RGB")
        pic = fit(im, pw, ph)
        canvas.paste(pic, (x + (pw - pic.size[0]) // 2, y0 + (ph - pic.size[1]) // 2))
        d.text((x, y0 + ph + 30), zh, font=cn(42), fill=TEXT)
        d.text((x + 130, y0 + ph + 44), eng, font=en(26, True), fill=MUTED)
        d.text((x, y0 + ph + 92), note, font=cn(26), fill=MUTED)

    d.text((70, H - 70), "TEMPLAR · BEFORE / AFTER · 2026-10-26", font=en(22), fill=MUTED)
    d.text((W - 340, H - 70), "圣殿骑士团 3D", font=cn(26), fill=MUTED)
    path = os.path.join(KIT, "before_after.png")
    canvas.save(path, optimize=True)
    print("[SHEET]", path, canvas.size)


def main():
    files = [f for f, *_ in ITEMS if os.path.exists(os.path.join(FINAL, f))]
    if not files:
        raise SystemExit(f"{FINAL} 里没有可拼的图")

    cols = 2
    rows = (len(files) + cols - 1) // cols
    cell_w, cell_h = 980, 1305
    cap_h = 190
    pad, gap = 70, 56
    head_h = 250
    W = pad * 2 + cols * cell_w + (cols - 1) * gap
    H = head_h + rows * (cell_h + cap_h + gap) + 90

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    d.text((pad, 66), "圣殿骑士 · 阶层装备对照", font=cn(76), fill=TEXT)
    d.text((pad + 4, 168), "ONE BODY  ·  FOUR RANKS  ·  KIT BY RANK", font=en(26, True), fill=MUTED)
    d.rectangle((pad, 218, pad + 120, 222), fill=ACCENT)

    picked = [i for i in ITEMS if i[0] in files]
    for idx, (fn, num, zh, eng, notes) in enumerate(picked):
        r, c = divmod(idx, cols)
        x = pad + c * (cell_w + gap)
        y = head_h + r * (cell_h + cap_h + gap)
        d.rounded_rectangle((x, y, x + cell_w, y + cell_h + cap_h - 26), 10, fill=PANEL)
        im = Image.open(os.path.join(FINAL, fn)).convert("RGB")
        pic = fit(im, cell_w - 28, cell_h - 24)
        canvas.paste(pic, (x + (cell_w - pic.size[0]) // 2, y + 12))
        d.text((x + 28, y + cell_h + 4), zh, font=cn(40), fill=TEXT)
        d.text((x + 28, y + cell_h + 58), eng, font=en(19, True), fill=MUTED)
        for j, line in enumerate(notes):
            d.text((x + 28, y + cell_h + 92 + j * 26), "· " + line, font=cn(19), fill=MUTED)
        d.text((x + cell_w - 72, y + 18), num, font=en(24, True), fill=DIM)

    d.text((pad, H - 62), "TEMPLAR RANK KIT  ·  1536×2048  ·  2026-10-26", font=en(21), fill=MUTED)
    d.text((W - 320, H - 64), "圣殿骑士团 3D", font=cn(25), fill=MUTED)

    path = os.path.join(KIT, "rank_compare.png")
    canvas.save(path, optimize=True)
    print("[SHEET]", path, canvas.size)

    manifest = {"project": "圣殿骑士团3D", "set": "rank_kit", "date": "2026-10-26",
                "generator": "MiniMax image-01", "size": [1536, 2048],
                "reference": "assets/concept/input/templar_tpose_20261026.jpg",
                "items": []}
    for fn, num, zh, eng, notes in ITEMS:
        p = os.path.join(FINAL, fn)
        if not os.path.exists(p):
            continue
        with Image.open(p) as im:
            size = list(im.size)
        meta = {"file": f"final/{fn}", "no": num, "zh": zh, "en": eng,
                "equipment": notes, "size": size}
        js = p[:-4] + ".json"
        if os.path.exists(js):
            meta["gen"] = json.load(open(js, encoding="utf-8"))
        manifest["items"].append(meta)
    mp = os.path.join(KIT, "manifest.json")
    json.dump(manifest, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[MANIFEST]", mp)


if __name__ == "__main__":
    before_after()
    main()
