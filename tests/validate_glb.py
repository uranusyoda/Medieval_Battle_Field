"""验证角色 GLB 的文件头、结构与基本资产约束。无需第三方依赖。"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "assets" / "models" / "characters" / "templar.glb"

# 程序化模型按部件拆分；Tripo 生成的是单一 mesh + 单材质，用 --loose 放宽
MIN_MESHES = 10
MIN_MATERIALS = 8


def main():
    global PATH, MIN_MESHES, MIN_MATERIALS
    args = sys.argv[1:]
    loose = "--loose" in args
    paths = [a for a in args if not a.startswith("--")]
    if paths:
        p = Path(paths[0])
        PATH = p if p.is_absolute() else ROOT / p
    if loose:
        MIN_MESHES, MIN_MATERIALS = 1, 1
    raw = PATH.read_bytes()
    magic, version, total = struct.unpack_from("<4sII", raw, 0)
    assert magic == b"glTF", "不是 GLB 文件"
    assert version == 2, "glTF 版本必须为 2"
    assert total == len(raw), "文件长度与 GLB 头不一致"
    json_length, chunk_type = struct.unpack_from("<II", raw, 12)
    assert chunk_type == 0x4E4F534A, "首个 chunk 必须是 JSON"
    doc = json.loads(raw[20:20 + json_length])
    primitives = [p for mesh in doc.get("meshes", []) for p in mesh["primitives"]]
    triangles = sum(
        doc["accessors"][p["indices"]]["count"] // 3
        for p in primitives if "indices" in p
    )
    assert len(doc.get("meshes", [])) >= MIN_MESHES, "角色应保持部件拆分"
    assert len(doc.get("materials", [])) >= MIN_MATERIALS, "PBR 材质缺失"
    assert triangles > 0, "模型没有三角面"
    print(f"PASS: {PATH.relative_to(ROOT)}")
    print(f"nodes={len(doc.get('nodes', []))}, meshes={len(doc['meshes'])}, "
          f"materials={len(doc['materials'])}, triangles={triangles}, bytes={len(raw)}")


if __name__ == "__main__":
    main()
