# 圣殿骑士团3D

以 Blender 程序化建模为起点的分层游戏工程。当前完成：**圣殿骑士静态角色模型 + GLB 导出 + 四视角渲染验收**。

**查看全部动画：** 双击 [查看全部动画.command](查看全部动画.command)，或打开 [HTML 动画展厅](http://127.0.0.1:8765/site/anatomical.html)（待机 / 行走 / 奔跑 / 跳跃 / 忍者低姿 / 握拳 / 逐指 / 转腕，共 8 套动作）。[展示说明与动画文件](docs/03_查看器/动画展示说明.md)。

**查看绑骨效果：** [绑骨效果索引](docs/03_查看器/绑骨效果索引.md)（60 骨人体结构版 · 全身 / 双手骨架 / 屈指对照 / 模型文件）。

2026-10-27 步态修订：行走 / 跑步采用 [CMU 真人动作](assets/mocap/cmu/README.md)重定向，60 FPS 平滑循环；行走收窄步宽，跑步改为闭合握拳。[直接查看行走正面](http://127.0.0.1:8765/site/anatomical.html?clip=walk&view=front#exhibit)。

## 目录

- `assets/`：概念、模型、材质、贴图、渲染图
- `maps/`：地图与关卡数据
- `src/`：游戏代码预留层（data / core / engine / view / app）
- `tools/`：Blender 等生产脚本
- `tests/`：资产与玩法验证
- `docs/`：架构与资产管线说明

详细分层见 `docs/01_架构/架构分层说明.md`。

## 当前角色产物

| 文件                                       | 用途                    |
| ---------------------------------------- | --------------------- |
| `assets/models/characters/templar.blend` | Blender 可编辑源文件        |
| `assets/models/characters/templar.glb`   | three.js / Godot 运行模型 |
| `assets/renders/templar_hero.png`        | 主视觉                   |
| `assets/renders/templar_front.png`       | 正面验收                  |
| `assets/renders/templar_side.png`        | 侧面验收                  |
| `assets/renders/templar_back.png`        | 背面验收                  |

> 注：`templar.blend / templar.glb` 目前不在磁盘上，需要时用 `tools/build_templar.py` 重新生成。

## Tripo 图生 3D（高精度源模型）

以 `assets/concept/templar_tpose.png`（无盾 T-pose）为输入，生成高面数带 PBR 贴图的模型：

| 文件 | 用途 |
| --- | --- |
| `assets/models/characters/templar_tpose.blend` | Blender 源文件（1.46M 三角面，含贴图） |
| `assets/models/characters/templar_tpose.glb` | 高精度 GLB（50 MB，3×4096 PBR） |
| `assets/renders/templar_tpose_{hero,front,side,back}.png` | 四视角验收 |

```bash
# 1) 生成（cn 站点；TRIPO_HOME 必须指到工作区内，否则写 history.jsonl 被沙箱拦）
export TRIPO_API_KEY=tsk_...
export TRIPO_HOME="$PWD/.tripo-home"
tripo make assets/concept/templar_tpose.png --for game-pc --model tripo-v3.1

# 2) 归一化 + 四视角验收 + 导出项目 GLB（--yaw -90 把 +X 朝向校到 -Y）
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/import_tripo.py -- \
  --glb tripo-out/templar_tpose/templar_tpose.glb --name templar_tpose --height 1.85 --yaw -90
```

### 无甲版 `templar_tpose_unarmored`（2026-10-26）

以 `assets/concept/input/templar_tpose_20261026.jpg`（亚麻内袍 / 皮靴 / 锁甲袖口，无甲无盾 T-pose）为输入，走同一条管线：

| 文件 | 用途 |
| --- | --- |
| `assets/models/characters/templar_tpose_unarmored.blend` | Blender 源文件（1.46M 三角面，含 3×4096 PBR） |
| `assets/models/characters/templar_tpose_unarmored.glb` | 高精度 GLB（54 MB），归一化到 1.85 m、脚底贴地、朝向已校到 -Y |
| `assets/renders/templar_tpose_unarmored_{hero,front,side,back}.png` | 四视角验收 |

```bash
# 1) 生成（game-pc 预设链尾是 convert:FBX，GLTF 原件不落盘，只回传 model.fbx）
export TRIPO_API_KEY=tsk_...
export TRIPO_HOME="$PWD/.tripo-home"
tripo make assets/concept/input/templar_tpose_20261026.jpg --for game-pc --model tripo-v3.1 \
  -o tripo-out/templar_tpose_unarmored

# 2) FBX → GLB（贴图内嵌，Blender 转一道）
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/fbx_to_glb.py -- \
  --fbx tripo-out/templar_tpose_unarmored/tripo-out/<task>/model.fbx \
  --out tripo-out/templar_tpose_unarmored/templar_tpose_unarmored.glb

# 3) 归一化 + 四视角验收 + 项目 GLB
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/import_tripo.py -- \
  --glb tripo-out/templar_tpose_unarmored/templar_tpose_unarmored.glb \
  --name templar_tpose_unarmored --height 1.85 --yaw -90
```

- 成本：image_to_model 40 credits + convert 5 credits = 45。
- 朝向实测：原始 FBX 已是 +Z 朝上、脸朝 +X、手臂沿 ±Y，所以只需 `--yaw -90`，不用改 pitch。
- 已知问题：袍摆后中片是一张零厚度单面板（参考图前开衩的延伸），进游戏前建议 Solidify 或删掉重做；五指仍是 Tripo 默认大张，绑骨时按 `--hand-gather / --hand-curl` 处理。
- 这一版本身**未绑骨**，是静态源模型；要能摆姿势用下面的**绑骨版**。

**绑骨版 `templar_tpose_unarmored_rigged`**（把上面那个模型复制一份再绑骨；原件保持未绑骨不动）：

| 文件 | 用途 |
| --- | --- |
| `assets/models/characters/templar_tpose_unarmored_rigged.blend` | 绑骨源文件（20 骨 + 蒙皮，动作未做） |
| `assets/models/characters/templar_tpose_unarmored_rigged.glb` | 运行模型 14 MB / 150k tris / 1 skin / **20 关节** / 3×2048 PBR，`JOINTS_0 + WEIGHTS_0` 齐全 |
| `assets/renders/templar_tpose_unarmored_rigged_hand.png` | 手部特写（rest pose，验证手指几何没被动过） |
| `assets/renders/templar_tpose_unarmored_rigged_pose_{front,threequarter}.png` | 绑骨后静态姿势验收（手臂下垂 15°、右腿前迈） |

骨骼只到大关节，**手当一个整体**：

```
root ─ hips ─ spine ─ chest ─ neck ─ head
                ├ shoulder.L ─ upper_arm.L ─ forearm.L ─ hand.L
                └ shoulder.R ─ upper_arm.R ─ forearm.R ─ hand.R
       ├ thigh.L ─ shin.L ─ foot.L
       └ thigh.R ─ shin.R ─ foot.R        （共 20 骨）
```

没有指骨、没有脚趾、没有披风/佩剑挂点。每边只有一根 `hand` 骨从腕部延伸到指尖，手的全部顶点权重 1.0 焊在这根骨上（`rigid_hands()`，L 1274 / R 1152 顶点），手指几何**一个点都没动**——原 Tripo 手型原样保留，摆姿势时整只手跟着前臂走，不会出现指头被压扁或拉丝。

```bash
# 绑骨（--preset body = 大关节 20 骨；--rigid-hands = 手焊成刚体；gather/curl 归零 = 不动手指几何）
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/rig_templar.py -- \
  --src templar_tpose_unarmored.blend --name templar_tpose_unarmored_rigged \
  --preset body --rigid-hands --hand-gather 0 --hand-curl 0 \
  --decimate 150000 --tex 2048
```

产物：`<name>.blend` + `<name>.glb`（带蒙皮）+ 三张验收图。实测：减面 1,464,270 → 150,000 三角面，贴图 4096 → 2048，bone heat 权重覆盖 75,559/75,559 顶点（0 未加权）。动作还没做，需要时再跑 `animate_templar.py`（目前它写死读 `templar_rig.blend`）。

> 有甲版 `templar_rig` 仍是老的 `--preset full`（25 骨，含脚趾 2 / 披风 2 / 佩剑挂点 1）并默认做手型收拢；两条路线互不影响。

## 绑骨与动作（Tripo 高模 → 游戏网格）

| 文件 | 用途 |
| --- | --- |
| `assets/models/characters/templar_rig.blend` | 绑骨源文件（25 骨 + 4 个 Action + NLA） |
| `assets/models/characters/templar_rig.glb` | 带蒙皮与动画的运行模型（17 MB / 150k tris / 3×2048 PBR） |
| `assets/renders/templar_anim_sheet.png` | 四套动作逐帧拼版 |
| `assets/renders/templar_anim_{walk,run,jump,crouch}.png` | 单动作逐帧 |

```bash
# 高模 → 游戏网格 + 骨架 + 蒙皮
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/rig_templar.py -- --decimate 150000 --tex 2048

# 四套动作 + 预览 + 导出 GLB
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/animate_templar.py
```

动作：`walk` 24 帧 / `run` 16 帧 / `jump` 36 帧 / `crouch` 32 帧，24 fps；walk / run / crouch 可循环，jump 为一次性。
骨架 25 根（含披风 2 根、左胯佩剑挂点 1 根）；着地帧自动按脚底最低点贴地。

手型：Tripo 的 T-pose 是五指大张的摊手，且没有指骨。`rig_templar.py` 蒙皮前做了两步几何处理（`--hand-gather 0.35` / `--hand-curl 22`），把手指往掌心中线收拢并轻压；四套动作再用 `rig_util.aim_palm()` 两向量定姿，让掌心始终朝大腿内侧，摆臂时不翻掌。收拢结果写进网格本身，GLB 直接继承。

```bash
# 动作总表（逐帧图 + 拼版）
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
  --python tools/anim_sheet.py
python3 tools/make_anim_sheet.py
```

## 2D 高清效果图（2026-10-26）

与 3D 模型并行的 2D 视觉资产，目录 `assets/concept/hd_effect/`：

| 文件 | 内容 | 尺寸 |
| --- | --- | --- |
| `templar_tpose_compare.png` | 无甲 / 有甲 T-pose 双联对照 | 2360×1980 |
| `templar_gear_sheet.png` | 9 件装备素材拼版 | 2520×3200 |
| `final/01_templar_tpose_unarmored.png` | 无甲 T-pose（亚麻内袍 / 皮靴） | 1536×2048 |
| `final/02_templar_tpose_armored.png` | 有甲 T-pose（桶盔 / 锁甲 / 红十字罩袍） | 1536×2048 |
| `final/03_templar_full_kit.png` | 全套装备英雄图（加鸢形盾） | 1536×2048 |
| `gear/01..09_*.jpg` | 盔 / 盾 / 剑 / 锁甲 / 靴 / 腰带 / 披风 / 手套 / 罩袍 | 1536×1536 |

```bash
python3 tools/gen_effect_2d.py gear        # 单件装备
python3 tools/make_effect_sheets.py        # 拼版 + manifest
```

流程、prompt 策略与已知问题见 `docs/02_资产管线/2D效果图生成.md`。

## 阶层装备图（2026-10-26）

以 `assets/concept/input/templar_tpose_20261026.jpg`（无甲 T-pose）为角色参考，按圣殿骑士团的
三个兄弟等级 + 突厥轻骑各出一张同姿态、同灰底的装备图，用来比对「阶层差异」：

| 文件 | 阶层 | 画面要点 |
| --- | --- | --- |
| `assets/concept/hd_effect/kit/final/01_knight_tpose.jpg` | 骑士兄弟（露脸） | 白罩袍 + 单一大十字 · 锁甲 · 锥盔 · 披风 |
| `assets/concept/hd_effect/kit/final/02_knight_helmed.jpg` | 骑士兄弟（闭盔） | 同上，闭面盔 · 无面部 |
| `assets/concept/hd_effect/kit/final/03_sergeant.jpg` | 军士兄弟 | 深褐罩袍 + 红十字 · 铁壶盔 · 甲更轻 |
| `assets/concept/hd_effect/kit/final/04_turcopole.jpg` | 突厥轻骑 | 棉甲 · 无锁甲 · 箭袋 |
| `assets/concept/hd_effect/kit/rank_compare.png` | 四阶层拼版 | 2156×3442，带中英标签 |
| `assets/concept/hd_effect/kit/final/05_full_kit.jpg` | 全套英雄图（加鸢形盾） | 盾面十字待修 |
| `assets/concept/hd_effect/kit/before_after.png` | 无甲 → 全装对照 | 2360×1980 |

```bash
python3 tools/gen_templar_kit.py knight 1505 1506
python3 tools/gen_templar_kit.py sergeant 1603
python3 tools/gen_templar_kit.py turcopole 1704
python3 tools/make_kit_sheet.py          # 拼版 + manifest
```

建制、各阶层装备对照与史实取舍见
[`docs/04_设定/圣殿骑士团建制与装备.md`](docs/04_设定/圣殿骑士团建制与装备.md)；
prompt 策略与踩坑见
[`docs/02_资产管线/2D效果图生成.md`](docs/02_资产管线/2D效果图生成.md) 第 9 节。

## 动作索引站（浏览器里看动作）

```bash
./tools/serve_site.sh          # → http://127.0.0.1:8765/site/
```

- 左栏「模型 · 骨骼状况」：`templar_rig`（已绑骨 · 25 骨 · 4 动作）/ `templar_tpose_unarmored`（未绑骨 · 0 骨 · 0 动作）/ `templar_tpose_unarmored_rigged`（绑骨版 · 20 骨 · 0 动作 · 手为整体），点卡片或按 `M` 切换，数字从 GLB 实测
- `?grid=1` 四联视图，四套动作同时播；`?clip=run` 直接选中某个动作；`?model=templar_tpose_unarmored` 直接开未绑骨高模
- 时间轴拖动、0.25×–2× 变速、循环开关、骨架显示、OrbitControls 转视角
- three.js 已 vendored 在 `site/vendor/`，断网可用；静态页，无构建步骤
- 自检：`node tools/check_site.mjs`（需 Chrome 开 9222 调试端口），26 项含骨骼状况

细节见 `docs/03_查看器/动作索引站.md`。

## 重新生成

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background --threads 4 --python tools/build_templar.py
```

## 验证 GLB

```bash
python3 tests/validate_glb.py                                  # 程序化模型（要求部件拆分）
python3 tests/validate_glb.py assets/models/characters/templar_tpose.glb --loose
```

`templar_rig` 已绑骨并带四套基础动作；LOD 分级、UV 展开与贴图烘焙、部件拆分仍待做。
