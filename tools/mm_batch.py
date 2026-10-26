# -*- coding: utf-8 -*-
"""MiniMax image-01 批量生成 helper（T-pose 探索用）。

python3 tools/mm_batch.py <prompt_file> <tag_prefix> <aspect> <seed> [no_ref] [...]
每组 = tag_prefix_aspect_seed
"""
import base64
import os
import sys
import time

import requests

VAULT = "/Users/yoda/WorkBuddy/2026-08-11-06-30-31/api-vault.env"
API = "https://api.minimax.chat/v1/image_generation"
OUT = "assets/concept/tpose"
REF = "assets/concept/refs/templar_hero_ref_768.jpg"


def load_key():
    for line in open(VAULT, encoding="utf-8"):
        if line.startswith("MINIMAX_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("no MINIMAX_API_KEY")


def data_uri(path):
    return "data:image/jpeg;base64," + base64.b64encode(open(path, "rb").read()).decode()


def gen(key, prompt, tag, aspect, seed, ref=None):
    body = {
        "model": "image-01",
        "prompt": prompt,
        "aspect_ratio": aspect,
        "response_format": "url",
        "n": 1,
        "prompt_optimizer": False,
        "aigc_watermark": False,
        "seed": seed,
    }
    if ref:
        body["subject_reference"] = [{"type": "character", "image_file": ref}]
    r = requests.post(
        API,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=300,
    )
    d = r.json()
    base = d.get("base_resp", {})
    if base.get("status_code") != 0:
        print(f"[FAIL] {tag}: {base}")
        return None
    img = requests.get(d["data"]["image_urls"][0], timeout=180).content
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{tag}.jpg")
    with open(path, "wb") as f:
        f.write(img)
    print(f"[OK] {path} ({len(img) // 1024} KB)")
    return path


if __name__ == "__main__":
    prompt_file, prefix = sys.argv[1], sys.argv[2]
    jobs = sys.argv[3:]  # aspect|seed[|ref]
    key = load_key()
    prompt = open(prompt_file, encoding="utf-8").read().strip()
    ref = data_uri(REF) if any(j.endswith(":ref") for j in jobs) else None
    for j in jobs:
        parts = j.split("|")
        aspect, seed = parts[0], int(parts[1])
        use_ref = len(parts) > 2 and parts[2] == "ref"
        tag = f"{prefix}_{aspect.replace(':', 'x')}_s{seed}" + ("_ref" if use_ref else "")
        gen(key, prompt, tag, aspect, seed, ref if use_ref else None)
        time.sleep(2)
