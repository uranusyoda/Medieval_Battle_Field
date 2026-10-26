# Blender 资产管线

## 当前产物

- `assets/models/characters/templar.blend`：可继续编辑的 Blender 源文件
- `assets/models/characters/templar.glb`：供 three.js / Godot 加载的运行模型
- `assets/renders/templar_{hero,front,side,back}.png`：主视觉与三视角验收图
- `tools/build_templar.py`：完整程序化建模脚本，可重复生成以上产物

## 重新生成

在 `圣殿骑士团3D/` 目录执行：

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background --threads 4 --python tools/build_templar.py
```

只渲染指定视角（仍会重建并导出模型）：

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background --python tools/build_templar.py -- hero front
```

## 模型结构

角色拆成独立部件：罩袍、胸前十字两片、锁子甲四肢、大桶盔、披风、腰带、鸢形盾、盾面十字、佩剑。`shield_root` 与 `sword_root` 是装备挂点，方便后续替换或拆分。

## 坐标与尺寸

- Blender 内：Z 向上，角色面朝 -Y，身高约 1.85m，脚底在 Z=0
- GLB 导出启用 `export_yup=True`，导入 three.js 后为 Y 向上
- 左手（+X）持盾，左髋佩剑

## 已知边界

- 当前是**静态模型**：未做骨骼绑定、动画、LOD、UV 展开与烘焙贴图
- 锁子甲和织物使用 Blender 程序纹理表达微表面，GLB 只保留基础 PBR 参数；引擎中要叠加 tiling 法线贴图才能还原细节
- 披风是静态曲面，不带布料模拟
- 盾面与胸前十字为独立几何片，便于后续替换阵营标识

## Tripo 图生 3D 流程（高精度源模型）

程序化模型（`build_templar.py`）保证部件拆分与可控面数，适合直接上战场；Tripo 图生 3D 提供**高精度、带 AI 推断细节的源模型**，适合定稿外观、做裁切贴图与重拓扑的起点。

### 输入

`assets/concept/templar_tpose.png`：无盾 T-pose、正面平光、灰底、全身入画（1152×864）。

### 生成

```bash
export TRIPO_API_KEY=tsk_...          # cn 站点
export TRIPO_HOME="$PWD/.tripo-home"  # 必须在工作区内：CLI 要写 history.jsonl，沙箱会拦截 ~/.tripo
tripo make assets/concept/templar_tpose.png --for game-pc --model tripo-v3.1
```

`--for game-pc` 展开为 `texture=true, pbr=true, texture_quality=detailed`（40 credits，约 3 分钟）。

### 归一化与验收

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/import_tripo.py -- \
  --glb tripo-out/templar_tpose/templar_tpose.glb \
  --name templar_tpose --height 1.85 --yaw -90
```

`import_tripo.py` 做四件事：拆父级空物体并把变换烘进网格（glTF 导入是四元数旋转模式，直接改 euler 无效）→ 按身高缩放到 1.85 m、脚底归零、XY 居中 → 导出 `templar_tpose.glb` 并存 `.blend` → 中性灰棚拍渲四视角。

Tripo 输出朝向是 +X，项目约定是 -Y，所以固定 `--yaw -90`。

### 当前规格（2026-10-26）

| 项 | 值 |
|---|---|
| 三角面 | 1,463,578（单 mesh） |
| 顶点 | 757,865 |
| 材质 | 1（BaseColor / NormalGL / ORM 各 4096²） |
| GLB | 50 MB |
| 包围盒 | 1.800 × 0.536 × 1.850 m，脚底 Z=0 |

### 已知边界

- **面数远超战场预算**（6k–9k tris）：这是高精度源，需重拓扑或减面后才算 LOD0
- **不拆件**：单 mesh，头盔/剑/披风未分离，换装与挂点需重新切分（Tripo 的 `mesh_segmentation` 可做，约 40 credits）
- **AI 推断偏差**：头盔偏圆顶且贴图给了镜面金属感（设定要求平顶桶盔 + 拉丝钢 roughness≈0.45）；胸前十字偏小
- 手部与锁子甲在单图生成下细节会糊，重要的话走 multiview（正/侧/背三视图，约 50 credits）重跑

## 骨骼与动作

### 管线

```bash
# 1) 高模 → 游戏网格 + 25 骨骨架 + 自动蒙皮（并渲静态姿态验收）
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/rig_templar.py -- --decimate 150000 --tex 2048

# 2) 四套动作 + 逐帧预览 + 导出带蒙皮的 GLB
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/animate_templar.py

# 3) 单动作逐帧检查
... --python tools/preview_anim.py -- walk 0 3 6 9 12 15 18 21
```

### 网格处理

Tripo 高模 1,463,578 tris → **149,914 tris**（Collapse 0.10），贴图 4096² → 2048²，顶点 95,917 → 75,859（合并重复点后 `bone heat` 才能收敛）。

### 骨架（25 根）

`root → hips → spine → chest → neck → head`；每侧 `shoulder / upper_arm / forearm / hand`、`thigh / shin / foot / toe`；另有 `cape.01 / cape.02`（披风两段）与 `sword`（左胯佩剑挂点，父级 hips）。

手臂骨骼不是水平摆放：从网格拟合出 T-pose 手臂实际有 **-0.191 的下垂斜率**，肩 1.369 m / 肘 1.307 m / 腕 1.259 m，骨骼沿这条轴走，否则蒙皮会扭。

姿态求解用「指向向量 + 最小扭转」：`rig_util.aim()` 把骨骼指向 armature 空间的目标方向，动画只需写方向，不用手调欧拉角。

手部单独走 `rig_util.aim_palm()`：同时给「手的方向」和「掌心朝向」，用两向量定姿（`R = R_target · R_rest⁻¹`）。只用 `aim()` 的 twist 是绕目标方向转固定角度，手臂前后摆时掌心会跟着翻，摆到某几帧就变成摊掌；两向量定姿则整段动作掌心都稳定朝大腿内侧。

### 手型处理（无指骨）

Tripo 给的是五指大张的 T-pose，手臂一垂下就成了两只「摊手掌」。`tools/rig_templar.py` 在蒙皮前做两步纯几何处理（`relax_hands()`，只动手指区、掌根不动，顶点权重与骨架都不变）：

| 参数 | 默认 | 作用 |
|---|---|---|
| `--hand-gather` | `0.35` | 绕掌心法线把手指往掌心中线合拢（扇形收拢） |
| `--hand-curl` | `22` | 绕指根轴把指尖往掌心方向压，避免手指像直叉 |

掌心法线取手背方向（+Y，源模型面朝 -Y）；只有手背明显不朝 +Y 时才退回指尖点云 PCA。处理后手型写进网格本身，四套动作与 GLB 都继承，不需要额外骨骼。

### 蒙皮

`ARMATURE_AUTO`（bone heat），75,859 / 75,859 顶点全部有权重；漏掉的顶点用最近骨段补。mesh 是单壳，没有部件拆分。

### 动作（24 fps，GLB 内按 NLA track 导出）

| 动作 | 帧 | 时长 | 循环 | 说明 |
|---|---|---|---|---|
| `walk` | 0–24 | 1.000 s | 是 | 接触 / 经过 ×2，摆臂与腿反向 |
| `run` | 0–16 | 0.667 s | 是 | 有腾空帧，前倾 0.18，摆臂加大 |
| `jump` | 0–36 | 1.500 s | 否 | 预备下蹲 → 蹬伸 → 顶点收腿 → 下落 → 落地缓冲 → 恢复 |
| `crouch` | 0–32 | 1.333 s | 是 | 蹲姿保持 + 呼吸起伏 |

### 自动贴地

每个着地关键帧会量出脚部顶点（foot/toe 权重 >0.3，共 4,576 个）的最低 Z，再把 hips 平移到位使其贴地，所以不需要手调 hips 高度。

逐帧实测最低脚底 Z：

| 动作 | 最低 | 最高 | 说明 |
|---|---|---|---|
| walk | -3 mm | +28 mm | 支撑脚贴地，摆动脚离地 3 cm |
| run | 0 | +142 mm | 腾空帧离地 14 cm |
| jump | -56 mm | +619 mm | 顶点离地 62 cm；第 9 帧（蹬伸前）穿地 5.6 cm |
| crouch | 0 | 0 | 全程贴地 |

### 已知边界

- **单 mesh 未拆件**：头盔/剑/披风与身体共用一套权重，剑跟随 hips，罩袍下摆被大腿带起，蹲下时布料会被压进腿里
- **跳跃第 9 帧脚底穿地 5.6 cm**：蹬伸前两帧的插值，需要在 f9 再加一个关键帧才能消掉
- **手型是烘焙进网格的松手**：收拢 + 屈指只改 T-pose 网格本身，五指不会独立动；抓握、挥手、持剑等需要独立手指的动作仍要加指骨（10~20 根）或换手模
- 没有 idle / 转身 / 攻击；`root` 骨未做位移，四套动作都是原地
