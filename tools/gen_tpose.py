# -*- coding: utf-8 -*-
"""用 MiniMax image-01 以 templar_hero 为角色参考，生成无盾牌 T-pose 效果图。

用法:
  python3 tools/gen_tpose.py test          # 连通性/参考图协议测试
  python3 tools/gen_tpose.py run           # 正式生成一批候选
"""
import base64
import json
import os
import sys
import time

import requests

VAULT = "/Users/yoda/WorkBuddy/2026-08-11-06-30-31/api-vault.env"
API = "https://api.minimax.chat/v1/image_generation"
OUT = "assets/concept/tpose"
REF = "assets/concept/refs/templar_hero_ref_768.jpg"

BASE_PROMPT = (
    'Strict T-pose character turnaround sheet of this Templar knight, front view, full body head to toe. Both arms raised perfectly horizontal at exact shoulder height in one straight line with the shoulders, elbows straight and locked, forearms continuing the horizontal line, hands open flat with fingers extended together, palms facing down, both arms symmetric. Legs straight, feet shoulder width apart, toes forward, body square to camera. NO shield anywhere, not held and not on the back. Sword fully sheathed in brown leather scabbard hanging at the left hip, only pommel and crossguard visible. Helmet: flat-topped cylindrical great helm, straight vertical sides, perfectly flat riveted top, single narrow horizontal eye slit, plain steel plate, absolutely no visible face or eyes, no pointed dome. Costume: long off-white linen surcoat to mid-calf with center front split, one large dark crimson cross on chest, chainmail on arms and legs, dark brown coarse wool cloak from the shoulders, brown leather belts with brass buckles, knee-high brown leather boots, no knee armor, no pauldrons, no gold trim, only the single red cross as decoration. Presentation: plain light grey seamless studio backdrop, even soft frontal diffuse light, no rim light, no vignette, no props, no text, centered with margins, photorealistic 12th century Knight Templar, 7.5 heads tall, orthographic 3D modeling reference.'
)


def load_key():
    with open(VAULT, encoding="utf-8") as f:
        for line in f:
            if line.startswith("MINIMAX_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("vault 中无 MINIMAX_API_KEY")


def gen(key, prompt, tag, seed=None, aspect="1:1", ref_b64=None, extra=None):
    body = {
        "model": "image-01",
        "prompt": prompt,
        "aspect_ratio": aspect,
        "response_format": "url",
        "n": 1,
        "prompt_optimizer": False,
        "aigc_watermark": False,
    }
    if seed is not None:
        body["seed"] = seed
    if ref_b64:
        body["subject_reference"] = [{"type": "character", "image_file": ref_b64}]
    if extra:
        body.update(extra)

    print(f"[submit] tag={tag} seed={seed} ref={'yes' if ref_b64 else 'no'} aspect={aspect}")
    r = requests.post(
        API,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=300,
    )
    if r.status_code != 200:
        print(f"[FAIL] HTTP {r.status_code}: {r.text[:400]}")
        return None
    data = r.json()
    base = data.get("base_resp", {})
    if base.get("status_code") != 0:
        print(f"[FAIL] api {base}")
        return None
    url = data["data"]["image_urls"][0]
    img = requests.get(url, timeout=180).content
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{tag}.png")
    with open(path, "wb") as f:
        f.write(img)
    print(f"[OK] {path} ({len(img) // 1024} KB)")
    return path


def main():
    key = load_key()
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    if mode == "test":
        with open(REF, "rb") as f:
            b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
        gen(key, BASE_PROMPT, "tpose_test", seed=1, ref_b64=b64)
        return

    with open(REF, "rb") as f:
        b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()

    jobs = [
        ("tpose_v2_ref_s111", 111, "1:1", BASE_PROMPT, True),
        ("tpose_v2_ref_s777", 777, "1:1", BASE_PROMPT, True),
        ("tpose_v2_txt_s333", 333, "1:1", BASE_PROMPT, False),
        ("tpose_v2_ref_s909", 909, "4:5", BASE_PROMPT, True),
    ]
    for tag, seed, aspect, prompt, use_ref in jobs:
        gen(key, prompt, tag, seed=seed, aspect=aspect, ref_b64=b64 if use_ref else None)
        time.sleep(2)


if __name__ == "__main__":
    main()
