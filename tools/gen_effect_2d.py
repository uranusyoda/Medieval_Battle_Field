# -*- coding: utf-8 -*-
"""圣殿骑士 · 2D 高清效果图生成（MiniMax image-01）

产出目录：assets/concept/hd_effect/
  drafts/   候选图（seed 命名，可复现）
  final/    选定成图（无甲 T-pose / 有甲 T-pose）
  gear/     全部装备单品图

用法示例：
  python3 tools/gen_effect_2d.py unarmored 101 202 303
  python3 tools/gen_effect_2d.py armored 401 402 --ref assets/concept/hd_effect/final/01_templar_tpose_unarmored.png
  python3 tools/gen_effect_2d.py gear
  python3 tools/gen_effect_2d.py gear great_helm
"""
import base64
import json
import os
import sys
import time

import requests

VAULT = "/Users/yoda/WorkBuddy/2026-08-11-06-30-31/api-vault.env"
API = "https://api.minimax.chat/v1/image_generation"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "concept", "hd_effect")
DRAFTS = os.path.join(OUT, "drafts")
FINAL = os.path.join(OUT, "final")
GEAR = os.path.join(OUT, "gear")

# 人物统一规格：3:4 竖幅，2048 高（image-01 上限）
CHAR_W, CHAR_H = 1536, 2048
GEAR_W, GEAR_H = 1536, 1536


def load_key():
    for line in open(VAULT, encoding="utf-8"):
        if line.startswith("MINIMAX_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("vault 中无 MINIMAX_API_KEY")


def data_uri(path):
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


# ---------------------------------------------------------------- Prompt
POSE = (
    "STRICT T-POSE: arms straight out to the sides at shoulder height, parallel to the floor. The "
    "shoulders, elbows and wrists form ONE straight horizontal line. The arms are exactly 90 degrees to "
    "the spine — not lowered, not angled down, not angled up. Elbows locked, wrists straight, palms facing "
    "the floor, fingers together pointing straight sideways, left and right perfectly symmetric. Legs "
    "straight, feet shoulder-width apart and flat, toes forward, body square to camera."
)

STYLE = (
    "Full-body character reference photo, front view, entire body head to soles inside frame, centered, "
    "plain light grey seamless studio backdrop, soft even frontal light, subtle grounded contact shadow, "
    "no props, no text, no watermark, photorealistic, ultra-detailed, sharp focus, 8k."
)

PROMPTS = {}

PROMPTS["unarmored"] = (
    "A 12th-century Knight Templar with NO armor, bare-headed, wearing only the linen under-layer: an "
    "off-white coarse linen tunic to mid-thigh with long sleeves and a simple fabric belt, dark brown wool "
    "trousers, knee-high worn brown leather boots. Absolutely no chainmail, no helmet, no shield, no sword, "
    "no armor plates, no bracers, no gloves, no wrist wraps, no cloak; bare forearms and bare hands. Face fully visible: man in his early 30s, short dark brown hair, "
    "short cropped beard, strong jaw, calm neutral expression, weathered sun-tanned skin, realistic anatomy, "
    "seven and a half heads tall. " + POSE + " " + STYLE
)

POSE_SHORT = (
    "STRICT T-POSE: arms straight out to the sides at shoulder height, parallel to the floor, shoulders, "
    "elbows and wrists on one straight line, not angled down or up, palms facing down, fingers together, "
    "legs straight and slightly apart, body square to the frontal camera."
)

STYLE_SHORT = (
    "Full-body front view, head to soles inside frame, plain light grey seamless studio backdrop, soft even "
    "frontal light, photorealistic, ultra-detailed, sharp focus, 8k, no text, no watermark."
)

PROMPTS["armored"] = (
    "A 12th-century Knight Templar in full armor, completely faceless. The head is fully enclosed in a "
    "CYLINDRICAL BUCKET-SHAPED GREAT HELM: straight-sided steel cylinder with a PERFECTLY FLAT HORIZONTAL "
    "TOP — no dome, no point, no spike, no ridge, no rounded crown; one narrow horizontal eye slit, riveted "
    "rim, no face, no skin, no eyes, no beard. Long-sleeved riveted chainmail hauberk to mid-thigh with "
    "coif, chausses and mail mittens; over the mail a long off-white linen surcoat to mid-calf with exactly "
    "ONE large dark crimson cross on the chest and no cross on the skirt; dark brown wool cloak from the "
    "shoulders; brown leather belt with aged brass buckle; sword in a brown leather scabbard at the left "
    "hip; knee-high brown leather boots. No shield. " + POSE_SHORT + " " + STYLE_SHORT
)

PROMPTS["armored_kit"] = (
    "Hero product shot of a 12th-century Knight Templar fully equipped. Flat-topped great helm with narrow "
    "eye slit, riveted chainmail hauberk and coif, off-white surcoat with one large dark crimson cross, dark "
    "brown wool cloak, leather belt with brass buckle, kite shield with off-white painted face and dark "
    "crimson cross strapped to the left forearm, sword in a brown leather scabbard at the left hip, knee-high "
    "leather boots. Slightly three-quarter view, dramatic soft studio light, plain warm grey seamless "
    "background, photorealistic, ultra-detailed steel, mail and linen, cinematic, 8k, no text, no watermark."
)

GEAR_PROMPTS = {
    "great_helm": (
        "Museum-quality product photograph of one medieval great helm, 12th century Templar style: "
        "PERFECTLY FLAT-TOPPED cylinder of cool brushed steel — the top is a flat horizontal disc, absolutely "
        "no dome, no point, no rounded crown. Straight vertical sides, riveted lower band, one narrow "
        "horizontal eye slit crossed by a short vertical breathing slit, no face, no plume, no gold, cool "
        "grey silver metal not bronze. Three-quarter view, floating slightly above the floor with a soft "
        "contact shadow, dark charcoal seamless studio background, dramatic soft sidelight and cool rim "
        "light, visible hammer marks, scratches and subtle patina, photorealistic, macro detail, 8k, "
        "clean image with no text, no letters, no signature, no watermark."
    ),
    "kite_shield": (
        "Museum-quality product photograph of one medieval kite shield, 12th century Templar style: "
        "tall tapered shield with rounded top corners and a pointed bottom, weathered off-white painted "
        "face, one large hand-painted dark crimson cross centered, thick brown leather rim with brass "
        "rivets, slightly curved front, old wood visible at chipped edges. Front view, centered, leaning "
        "against nothing, soft contact shadow, dark charcoal seamless studio background, dramatic soft "
        "sidelight, photorealistic, ultra-detailed paint cracks and leather grain, 8k, no text."
    ),
    "arming_sword": (
        "Museum-quality product photograph of one medieval arming sword with its brown leather scabbard, "
        "12th century: straight double-edged blade, simple straight crossguard of aged brass, leather-"
        "wrapped grip, round brass pommel, brown leather scabbard with brass chape. Diagonal composition, "
        "the sword partially drawn from the scabbard showing the blade, dark charcoal seamless studio "
        "background, dramatic soft sidelight, photorealistic, macro detail of steel grain, leather and "
        "patina, 8k, no text, no watermark."
    ),
    "mail_hauberk": (
        "Museum-quality product photograph of a riveted chainmail hauberk with integrated coif, 12th "
        "century: dense dark steel rings, riveted and alternating, draped over an invisible stand so the "
        "sleeves and skirt fall naturally, coif opening at the top. Dark charcoal seamless studio "
        "background, dramatic soft sidelight and cool rim light, extreme detail of individual interlocking "
        "rings, subtle oiled sheen, photorealistic, macro, 8k, no text, no watermark."
    ),
    "leather_boots": (
        "Museum-quality product photograph of a pair of medieval knee-high leather boots, 12th century: "
        "dark brown oiled leather, soft creases at the ankle, wrap-around leather straps with small brass "
        "buckles, rounded toes, worn soles. Standing side by side, three-quarter view, dark charcoal "
        "seamless studio background, dramatic soft sidelight, photorealistic, ultra-detailed leather grain "
        "and stitching, 8k, no text, no watermark."
    ),
    "leather_belt": (
        "Museum-quality product photograph of a medieval brown leather belt with an aged brass buckle, "
        "12th century: thick oiled leather strap coiled in a loose spiral, hand-forged brass buckle and "
        "strap end, visible stitching and wear. Top three-quarter view, dark charcoal seamless studio "
        "background, dramatic soft sidelight, photorealistic, macro detail of leather grain and patina, "
        "8k, no text, no watermark."
    ),
    "wool_cloak": (
        "Museum-quality product photograph of a medieval dark brown coarse wool cloak with a hood, 12th "
        "century: heavy felted wool, deep natural folds, simple bronze clasp at the neck, slightly frayed "
        "hem. Hanging from a plain wooden peg against a dark charcoal seamless studio background, dramatic "
        "soft sidelight, photorealistic, ultra-detailed wool fibers, 8k, no text, no watermark."
    ),
    "leather_gloves": (
        "Museum-quality product photograph of a pair of medieval brown leather gloves, 12th century: soft "
        "oiled deerskin, simple stitched seams, slightly worn fingertips, laid out side by side on a dark "
        "stone surface. Dark charcoal seamless studio background, dramatic soft sidelight, photorealistic, "
        "macro detail of leather grain and stitching, 8k, no text, no watermark."
    ),
    "surcoat": (
        "Museum-quality product photograph of a medieval Knight Templar surcoat, 12th century: long "
        "off-white coarse linen sleeveless surcoat with a center front split, one large hand-painted dark "
        "crimson cross on the chest, slightly frayed hem. Hanging on a simple wooden hanger against a dark "
        "charcoal seamless studio background, dramatic soft sidelight, photorealistic, ultra-detailed linen "
        "weave and paint texture, 8k, no text, no watermark."
    ),
}


# ---------------------------------------------------------------- 生成
def gen(key, prompt, tag, w, h, seed=None, ref=None, out_dir=DRAFTS, fmt="png"):
    body = {
        "model": "image-01",
        "prompt": prompt,
        "width": w,
        "height": h,
        "response_format": "url",
        "n": 1,
        "prompt_optimizer": False,
        "aigc_watermark": False,
    }
    if seed is not None:
        body["seed"] = seed
    if ref:
        body["subject_reference"] = [{"type": "character", "image_file": data_uri(ref)}]

    data = None
    for attempt in range(3):
        print(f"[submit] {tag} {w}x{h} seed={seed} ref={os.path.basename(ref) if ref else '-'} try={attempt+1}")
        r = requests.post(API, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json=body, timeout=300)
        if r.status_code != 200:
            print(f"[FAIL] HTTP {r.status_code}: {r.text[:300]}")
            time.sleep(3)
            continue
        data = r.json()
        base = data.get("base_resp", {})
        if base.get("status_code") == 0:
            break
        print(f"[FAIL] api {base}")
        if base.get("status_code") not in (1000, 1002):
            return None
        time.sleep(5)
    if not data or data.get("base_resp", {}).get("status_code") != 0:
        return None
    url = data["data"]["image_urls"][0]
    img = requests.get(url, timeout=180).content
    os.makedirs(out_dir, exist_ok=True)
    base_path = os.path.join(out_dir, tag)
    with open(base_path + ".raw", "wb") as f:
        f.write(img)
    from PIL import Image
    im = Image.open(base_path + ".raw")
    im.load()
    fmt = "jpg" if im.format in ("JPEG", "MPO") else (im.format or "PNG").lower()
    path = f"{base_path}.{fmt}"
    im.convert("RGB").save(path, quality=95, subsampling=0)
    os.remove(base_path + ".raw")
    print(f"[OK] {path} ({os.path.getsize(path) // 1024} KB)")
    with open(os.path.join(out_dir, f"{tag}.json"), "w", encoding="utf-8") as f:
        json.dump({"tag": tag, "seed": seed, "width": w, "height": h,
                   "ref": os.path.relpath(ref, ROOT) if ref else None, "prompt": prompt}, f,
                  ensure_ascii=False, indent=2)
    return path


def main():
    key = load_key()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    mode = args[0]

    if mode in ("unarmored", "armored", "armored_kit"):
        seeds = [int(a) for a in args[1:] if a.isdigit()] or [101, 202, 303]
        ref = None
        if "--ref" in args:
            ref = args[args.index("--ref") + 1]
        elif mode != "unarmored":
            ref = os.path.join(OUT, "final", "01_templar_tpose_unarmored.png")
            if not os.path.exists(ref):
                raise SystemExit(f"缺少无甲基准图：{ref}")
        for s in seeds:
            gen(key, PROMPTS[mode], f"{mode}_s{s}", CHAR_W, CHAR_H, seed=s, ref=ref)
            time.sleep(2)
        return

    if mode == "final":
        # 把选定候选复制成正式文件名：final <tag> <target>
        src = os.path.join(DRAFTS, args[1] + ".png")
        dst = os.path.join(FINAL, args[2] + ".png")
        os.makedirs(FINAL, exist_ok=True)
        with open(src, "rb") as f, open(dst, "wb") as g:
            g.write(f.read())
        print("[FINAL]", dst)
        return

    if mode == "gear":
        keys = args[1:] or list(GEAR_PROMPTS)
        for i, k in enumerate(keys, 1):
            if k not in GEAR_PROMPTS:
                raise SystemExit(f"未知装备：{k}")
            tag = f"{i:02d}_{k}"
            gen(key, GEAR_PROMPTS[k], tag, GEAR_W, GEAR_H, seed=700 + i, out_dir=GEAR)
            time.sleep(2)
        return

    print(__doc__)


if __name__ == "__main__":
    main()
