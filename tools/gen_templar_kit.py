# -*- coding: utf-8 -*-
"""圣殿骑士 · 按建制阶层给同一角色上装备（MiniMax image-01，角色参考 = 无甲 T-pose）

输入基准：assets/concept/input/templar_tpose_20261026.jpg（无甲 T-pose，已经被 Tripo 转成
templar_tpose_unarmored 三维模型）。本脚本以它为 subject_reference，保持人物身份与 T-pose，
按「骑士兄弟 / 军士兄弟 / 突厥轻骑」三个阶层分别生成全身装备图。

产出：assets/concept/hd_effect/kit/

用法：
  python3 tools/gen_templar_kit.py knight 1201 1202     # 骑士兄弟（大桶盔，无脸）
  python3 tools/gen_templar_kit.py knight_open 1211      # 骑士兄弟（锥盔，露脸）
  python3 tools/gen_templar_kit.py sergeant 1301         # 军士兄弟（深褐罩袍 / 铁壶盔）
  python3 tools/gen_templar_kit.py turcopole 1401        # 突厥轻骑（无锁甲，弓）
  python3 tools/gen_templar_kit.py final knight_s1201 01_knight
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
KIT = os.path.join(OUT, "kit")
REF = os.path.join(ROOT, "assets", "concept", "input", "templar_tpose_20261026.jpg")

W, H = 1536, 2048


def load_key():
    for line in open(VAULT, encoding="utf-8"):
        if line.startswith("MINIMAX_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("vault 中无 MINIMAX_API_KEY")


def masked_ref():
    """把参考图的头部涂成中性灰，避免模型照抄裸头、拒绝戴盔。"""
    path = os.path.join(KIT, "_ref_maskhead.jpg")
    if os.path.exists(path):
        return path
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.open(REF).convert("RGB")
    w, h = im.size
    d = ImageDraw.Draw(im)
    d.ellipse((int(w * 0.415), int(h * 0.070), int(w * 0.585), int(h * 0.235)), fill=(110, 114, 120))
    im = im.filter(ImageFilter.GaussianBlur(6))
    os.makedirs(KIT, exist_ok=True)
    im.save(path, quality=95)
    print(f"[mask] {path}")
    return path


def data_uri(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


# ---------------------------------------------------------------- Prompt
# API 限制：prompt 必须 < 1500 字符（超出报 2013），所以约束写成短句
POSE = (
    "STRICT T-POSE: arms straight out sideways at shoulder height, parallel to the floor, "
    "shoulders-elbows-wrists on one straight horizontal line, arms exactly 90 degrees to the spine, "
    "not lowered, not bent; palms down, fingers together; legs straight, feet shoulder-width, toes "
    "forward, body square to camera."
)

STYLE = (
    "Full-body front view, head to soles inside frame, centered, plain light grey seamless studio "
    "backdrop, soft even frontal light, subtle contact shadow, no text, no watermark, photorealistic, "
    "ultra-detailed, 8k."
)

SAME = (
    "The SAME man as the reference photo: same build, same broad shoulders, same strict T-pose, same "
    "camera distance; only his clothing changes - he is now fully equipped as a Templar."
)

PROMPTS = {}

# 骑士兄弟：白罩袍 + 单一红十字 + 锁甲 + 平顶大桶盔（与项目概念设定一致）
PROMPTS["knight"] = (
    SAME + " A 13th-century brother knight of the Temple. Off-white padded linen gambeson at collar and "
    "cuffs; long-sleeved riveted steel chainmail hauberk to mid-thigh, mail chausses, mail mittens; over "
    "it a sleeveless off-white linen surcoat to mid-calf, plain skirt, exactly ONE large dark crimson "
    "straight-armed cross on the chest; wide dark brown leather belt with brass buckle; a plain brown "
    "leather scabbard hanging empty at his left hip, both hands empty, no weapon in his hands; dark "
    "brown wool cloak behind the arms; knee-high brown leather boots. Head completely covered by a great helm: "
    "a steel cylinder, flat top like an upturned bucket, no dome, no point, no crest, one narrow "
    "horizontal eye slit, completely faceless, no skin, no eyes, no beard. No shield, no gold, no plate "
    "armour. " + POSE + " " + STYLE
)

# 骑士兄弟·露脸：锁甲头巾 + 锥形鼻甲盔（12 世纪）
PROMPTS["knight_open"] = (
    SAME + " A 12th-century brother knight of the Temple, face visible. Riveted steel chainmail hauberk to "
    "mid-thigh, mail coif around neck and shoulders, mail chausses, bare hands; sleeveless off-white "
    "linen surcoat to mid-calf, plain skirt, exactly ONE large dark crimson straight-armed cross on the "
    "chest; wide brown leather belt with brass buckle; sword in a brown leather scabbard at his left hip; "
    "knee-high brown leather boots; dark brown wool cloak behind him. On his head a plain conical steel "
    "nasal helmet with a narrow nose guard, no crest, over a padded arming cap; his short dark hair, "
    "cropped beard, strong jaw and calm expression fully visible. No shield, no gold, no plate armour. "
    + POSE + " " + STYLE
)

# 军士兄弟：深褐罩袍 + 红十字 + 无袖锁甲 + 铁壶盔（规则：军士穿黑/褐，不穿白）
PROMPTS["sergeant"] = (
    SAME + " A 12th-century sergeant brother of the Temple, a mounted sergeant, not a knight. Padded "
    "leather jerkin under a SLEEVELESS riveted steel chainmail hauberk to mid-thigh, bare forearms in "
    "linen sleeves, mail chausses without foot coverings; over the mail a dark brown almost black coarse "
    "wool surcoat to mid-calf, exactly ONE dark crimson cross sewn straight onto the dark wool, plain "
    "skirt, no white cloth anywhere, no white panel or shield shape on the chest, he is not entitled to "
    "the white habit; plain brown leather belt; knee-high brown leather "
    "boots. On his head an open-faced iron kettle hat with a wide brim and low crown, over a mail coif, "
    "his face, short beard and jaw visible. Short sword in a brown leather scabbard at his left hip. No "
    "shield, no cloak, no gold, no plate armour. " + POSE + " " + STYLE
)

# 突厥轻骑：无锁甲，厚棉甲 / 皮甲，弓与箭袋，不穿白袍
PROMPTS["turcopole"] = (
    SAME + " A turcopole, a lightly armed mounted archer of the Templars' auxiliary cavalry, 12th-century "
    "Levant. Thick quilted off-white cotton aketon gambeson to mid-thigh, visible vertical quilting, "
    "brown leather belt, loose dark brown wool trousers, knee-high soft brown leather riding boots, short "
    "brown cloak over one shoulder. NO chainmail anywhere, not even on the arms, bare forearms. On his "
    "head a soft pointed wool cap. A leather quiver of arrows at his right hip. Face fully visible, sun-tanned, short dark beard. No white surcoat, no red cross, no "
    "shield, no gold, no plate armour. " + POSE + " " + STYLE
)

# 需要「换头」的阶层：把参考图的头遮成灰色，模型才会按 prompt 造盔（否则会照抄参考图的裸头）
MASK_HEAD = {"knight", "knight_open", "sergeant"}

for _k, _v in PROMPTS.items():
    print(f"[prompt] {_k}: {len(_v)} chars")

# ---------------------------------------------------------------- 生成
def gen(key, prompt, tag, seed=None, ref=REF, out_dir=KIT):
    body = {
        "model": "image-01",
        "prompt": prompt,
        "width": W,
        "height": H,
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
        print(f"[submit] {tag} {W}x{H} seed={seed} try={attempt + 1}")
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
    print(f"[OK] {path} ({os.path.getsize(path) // 1024} KB) {im.size[0]}x{im.size[1]}")
    with open(os.path.join(out_dir, f"{tag}.json"), "w", encoding="utf-8") as f:
        json.dump({"tag": tag, "seed": seed, "width": W, "height": H,
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

    if mode in PROMPTS:
        seeds = [int(a) for a in args[1:] if a.isdigit()] or [1]
        ref = masked_ref() if mode in MASK_HEAD else REF
        for s in seeds:
            gen(key, PROMPTS[mode], f"{mode}_s{s}", seed=s, ref=ref)
            time.sleep(2)
        return

    if mode == "final":
        src_tag, dst_tag = args[1], args[2]
        for ext in ("jpg", "png"):
            src = os.path.join(KIT, f"{src_tag}.{ext}")
            if os.path.exists(src):
                dst = os.path.join(KIT, "final", f"{dst_tag}.{ext}")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(src, "rb") as f, open(dst, "wb") as g:
                    g.write(f.read())
                print(f"[final] {dst}")
                return
        raise SystemExit(f"找不到 {src_tag}")

    print(__doc__)


if __name__ == "__main__":
    main()
