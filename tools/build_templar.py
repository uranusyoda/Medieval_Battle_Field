"""圣殿骑士 · Blender 程序化建模
用法: Blender --background --python tools/build_templar.py
产出: assets/models/characters/templar.blend + templar.glb, assets/renders/*.png
坐标: Z 向上, 角色面朝 -Y, 身高 1.85m。左手(+X)持盾, 左髋佩剑。
"""
import bpy
import math
import os
import sys
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "assets", "models", "characters")
RENDERS = os.path.join(ROOT, "assets", "renders")
os.makedirs(MODELS, exist_ok=True)
os.makedirs(RENDERS, exist_ok=True)

# ---------------------------------------------------------------- 场景重置
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.curves):
    pass

# ---------------------------------------------------------------- 材质
def mat(name, hex_color, metallic=0.0, roughness=0.9, weave=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    rgb = tuple(int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    # 十六进制按 sRGB 输入, 转线性, 避免渲染偏亮
    lin = tuple(((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in rgb)
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*lin, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    m.diffuse_color = (*lin, 1.0)
    if weave:  # 仅 Blender 内有效的织物凹凸, GLB 不导出程序纹理
        noise = m.node_tree.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 220.0
        bump = m.node_tree.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.25
        bump.inputs["Distance"].default_value = 0.004
        m.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        m.node_tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m

CLOTH = mat("surcoat_linen", "DDD6C6", roughness=0.95, weave=True)
CROSS = mat("cross_crimson", "9E2B25", roughness=0.85)
MAIL = mat("chainmail_steel", "5A5E63", metallic=0.85, roughness=0.5, weave=True)
HELM = mat("helm_steel", "6E7278", metallic=0.9, roughness=0.42)
LEATHER = mat("leather_dark", "4A3527", roughness=0.72)
BRASS = mat("brass_aged", "8A6E3C", metallic=0.85, roughness=0.55)
CLOAK = mat("cloak_wool", "2B2724", roughness=0.97, weave=True)
DARK = mat("interior_dark", "0B0B0C", roughness=1.0)
SHIELD_WHITE = mat("shield_paint", "D8D2C4", roughness=0.8)

PARTS = []

def register(obj, name, material):
    obj.name = name
    if material:
        obj.data.materials.append(material)
    PARTS.append(obj)
    return obj

def smooth(obj):
    if obj.type == "MESH":
        for p in obj.data.polygons:
            p.use_smooth = True
    return obj

def bevel(obj, width=0.01, segments=2):
    mod = obj.modifiers.new("bevel", "BEVEL")
    mod.width = width
    mod.segments = segments
    return obj

def cube(name, loc, scale, material, bev=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    o = bpy.context.object
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    register(o, name, material)
    if bev:
        bevel(o, bev)
    return o

def cyl(name, loc, radius, depth, material, vertices=24, r2=None):
    if r2 is None:
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    else:
        bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius, radius2=r2, depth=depth, location=loc)
    o = register(bpy.context.object, name, material)
    return smooth(o)

def sphere(name, loc, scale, material, seg=20, rings=12):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=rings, radius=1.0, location=loc)
    o = bpy.context.object
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return smooth(register(o, name, material))

def mesh_obj(name, verts, faces, material):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return register(o, name, material)

def solidify(obj, thickness=0.006):
    mod = obj.modifiers.new("solidify", "SOLIDIFY")
    mod.thickness = thickness
    return obj

# ---------------------------------------------------------------- 罩袍(放样圆环)
# (z, 半宽, 半深) 由下到上
RINGS = [
    (0.55, 0.300, 0.200),
    (0.70, 0.282, 0.188),
    (0.85, 0.250, 0.168),
    (0.95, 0.208, 0.142),
    (1.02, 0.188, 0.128),
    (1.15, 0.212, 0.148),
    (1.32, 0.246, 0.158),
    (1.42, 0.248, 0.140),
    (1.47, 0.196, 0.112),
    (1.50, 0.095, 0.085),
]
SEG = 32

def ring_profile(z):
    """按高度线性插值罩袍截面, 供十字贴花精确贴合布面"""
    if z <= RINGS[0][0]:
        return RINGS[0][1], RINGS[0][2]
    if z >= RINGS[-1][0]:
        return RINGS[-1][1], RINGS[-1][2]
    for i in range(len(RINGS) - 1):
        z0, w0, d0 = RINGS[i]
        z1, w1, d1 = RINGS[i + 1]
        if z0 <= z <= z1:
            t = (z - z0) / (z1 - z0)
            return w0 + (w1 - w0) * t, d0 + (d1 - d0) * t
    return RINGS[-1][1], RINGS[-1][2]

verts, faces = [], []
for z, w, d in RINGS:
    for i in range(SEG):
        a = 2 * math.pi * i / SEG
        verts.append((w * math.cos(a), d * math.sin(a), z))
for r in range(len(RINGS) - 1):
    for i in range(SEG):
        a = r * SEG + i
        b = r * SEG + (i + 1) % SEG
        faces.append((a, b, b + SEG, a + SEG))
surcoat = smooth(mesh_obj("surcoat", verts, faces, CLOTH))
solidify(surcoat, 0.008)
sub = surcoat.modifiers.new("subdiv", "SUBSURF")
sub.levels = 1
sub.render_levels = 1

def cloth_point(x, z, lift=0.004):
    w, d = ring_profile(z)
    ratio = min(abs(x) / max(w, 1e-5), 0.999)
    y = -d * math.sqrt(1.0 - ratio * ratio) - lift
    return (x, y, z)

def cloth_patch(name, x0, x1, z0, z1, material, nx=10, nz=4):
    """在罩袍正面贴一块跟随布面曲率的布贴(用于红十字)"""
    vs, fs = [], []
    for j in range(nz + 1):
        z = z0 + (z1 - z0) * j / nz
        for i in range(nx + 1):
            x = x0 + (x1 - x0) * i / nx
            vs.append(cloth_point(x, z))
    for j in range(nz):
        for i in range(nx):
            a = j * (nx + 1) + i
            fs.append((a, a + 1, a + nx + 2, a + nx + 1))
    return smooth(mesh_obj(name, vs, fs, material))

# 胸前大十字: 竖臂 + 横臂
cloth_patch("cross_vertical", -0.038, 0.038, 1.055, 1.400, CROSS, nx=4, nz=16)
cloth_patch("cross_horizontal", -0.150, 0.150, 1.240, 1.316, CROSS, nx=14, nz=4)

# ---------------------------------------------------------------- 锁子甲与四肢
# 颈部锁子甲(coif)
cyl("mail_coif", (0, 0, 1.485), 0.098, 0.13, MAIL)
sphere("mail_shoulders_L", (0.235, 0, 1.415), (0.085, 0.095, 0.085), MAIL)
sphere("mail_shoulders_R", (-0.235, 0, 1.415), (0.085, 0.095, 0.085), MAIL)

def limb(name, p0, p1, r0, r1, material):
    p0, p1 = Vector(p0), Vector(p1)
    mid = (p0 + p1) / 2
    o = cyl(name, mid, r0, (p1 - p0).length, material, r2=r1)
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = (p1 - p0).to_track_quat("Z", "Y")
    return o

for side, sx in (("L", 1.0), ("R", -1.0)):
    shoulder = (sx * 0.255, 0.0, 1.415)
    elbow = (sx * 0.330, -0.015, 1.150)
    wrist = (sx * 0.352, -0.055, 0.935)
    limb(f"mail_upperarm_{side}", shoulder, elbow, 0.072, 0.060, MAIL)
    limb(f"mail_forearm_{side}", elbow, wrist, 0.060, 0.046, MAIL)
    sphere(f"mail_elbow_{side}", elbow, (0.062, 0.062, 0.062), MAIL)
    # 手: 简化皮手套
    hand = sphere(f"glove_{side}", (sx * 0.358, -0.062, 0.885), (0.048, 0.036, 0.062), LEATHER)
    # 腿: 锁子甲裤 + 皮靴
    hip = (sx * 0.105, 0.0, 0.72)
    ankle = (sx * 0.115, -0.005, 0.16)
    limb(f"mail_leg_{side}", hip, ankle, 0.085, 0.058, MAIL)
    cyl(f"boot_{side}", (sx * 0.115, -0.005, 0.135), 0.066, 0.24, LEATHER)
    foot = cube(f"foot_{side}", (sx * 0.115, -0.055, 0.045), (0.125, 0.245, 0.09), LEATHER, bev=0.03)

# ---------------------------------------------------------------- 腰带与带扣
bv, bf = [], []
BELT_Z0, BELT_Z1 = 0.995, 1.055
for z in (BELT_Z0, BELT_Z1):
    w, d = ring_profile(z)
    for i in range(SEG):
        a = 2 * math.pi * i / SEG
        bv.append(((w + 0.012) * math.cos(a), (d + 0.012) * math.sin(a), z))
for i in range(SEG):
    bf.append((i, (i + 1) % SEG, (i + 1) % SEG + SEG, i + SEG))
belt = smooth(mesh_obj("belt", bv, bf, LEATHER))
solidify(belt, 0.010)
cube("belt_buckle", (0.02, -0.152, 1.025), (0.075, 0.02, 0.055), BRASS, bev=0.006)
cube("belt_buckle_hole", (0.02, -0.163, 1.025), (0.045, 0.006, 0.030), DARK)
# 斜跨剑带
strap = cube("sword_strap", (0.10, -0.145, 1.10), (0.30, 0.014, 0.045), LEATHER, bev=0.004)
strap.rotation_euler[1] = math.radians(-28)

# ---------------------------------------------------------------- 大桶盔
HELM_Z = 1.685
helm = cyl("great_helm", (0, 0, HELM_Z), 0.148, 0.335, HELM, vertices=32)
# 内衬(让眼缝看起来是黑洞)
cyl("helm_interior", (0, 0, HELM_Z - 0.01), 0.130, 0.32, DARK, vertices=24)
# 顶部微凸盖
cyl("helm_top", (0, 0, HELM_Z + 0.170), 0.150, 0.016, HELM, vertices=32)
# 底部加强圈
cyl("helm_rim", (0, 0, HELM_Z - 0.150), 0.152, 0.026, HELM, vertices=32)

def cut_slot(target, name, loc, scale):
    cutter = cube(name, loc, scale, None)
    mod = target.modifiers.new("slot", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    bpy.context.view_layer.objects.active = target
    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except Exception as exc:
        print("boolean failed:", exc)
    bpy.data.objects.remove(cutter, do_unlink=True)
    PARTS.remove(cutter)  #  cutter 已销毁, 必须从登记册移除

# 十字眼缝: 横缝 + 竖缝
cut_slot(helm, "slot_h", (0, -0.135, HELM_Z + 0.030), (0.240, 0.090, 0.020))
cut_slot(helm, "slot_v", (0, -0.135, HELM_Z - 0.010), (0.018, 0.090, 0.130))
bevel(helm, 0.006, 2)
# 铆钉
for i in range(10):
    a = 2 * math.pi * i / 10
    sphere(f"helm_rivet_{i:02d}",
           (0.151 * math.cos(a), 0.151 * math.sin(a), HELM_Z - 0.150),
           (0.008, 0.008, 0.008), BRASS, seg=8, rings=6)

# ---------------------------------------------------------------- 披风
cv, cf = [], []
CL_ROWS, CL_COLS = 14, 26
for j in range(CL_ROWS + 1):
    t = j / CL_ROWS                      # 0=肩 1=下摆
    z = 1.470 - t * 1.190
    radius = 0.175 + t * 0.115
    spread = math.radians(58 + t * 30)   # 背后扇形张开
    for i in range(CL_COLS + 1):
        s = i / CL_COLS
        a = math.pi / 2 - spread + 2 * spread * s   # 以 +Y 为中心
        wave = math.sin(s * math.pi * 7) * (0.012 + t * 0.030)
        r = radius + wave
        hem = (math.sin(s * math.pi * 5) * 0.035 * t * t)
        cv.append((r * math.cos(a), r * math.sin(a) + 0.02, z + hem))
for j in range(CL_ROWS):
    for i in range(CL_COLS):
        a = j * (CL_COLS + 1) + i
        cf.append((a, a + 1, a + CL_COLS + 2, a + CL_COLS + 1))
cloak = smooth(mesh_obj("cloak", cv, cf, CLOAK))
solidify(cloak, 0.007)

# ---------------------------------------------------------------- 鸢形盾(+X 手)
# 盾面局部坐标: u 横向, v 纵向; 用 u^2 给出弧度
SHIELD_OUTLINE = [
    (-0.230, 0.330), (0.230, 0.330), (0.235, 0.130),
    (0.190, -0.060), (0.110, -0.230), (0.000, -0.360),
    (-0.110, -0.230), (-0.190, -0.060), (-0.235, 0.130),
]
SHIELD_CURVE = 0.55

def shield_point(u, v, lift=0.0):
    return (u, -SHIELD_CURVE * u * u - lift, v)

def build_shield():
    # 用扇形三角化(凸多边形), 中心略鼓
    vs = [shield_point(0, 0.0)]
    for u, v in SHIELD_OUTLINE:
        vs.append(shield_point(u, v))
    fs = []
    n = len(SHIELD_OUTLINE)
    for i in range(n):
        fs.append((0, i + 1, (i + 1) % n + 1))
    body = smooth(mesh_obj("shield_body", vs, fs, SHIELD_WHITE))
    solidify(body, 0.022).modifiers["solidify"].offset = 0  # 厚度向两侧均分, 避免盖住十字
    # 皮革包边
    for i in range(n):
        u0, v0 = SHIELD_OUTLINE[i]
        u1, v1 = SHIELD_OUTLINE[(i + 1) % n]
        p0 = Vector(shield_point(u0, v0))
        p1 = Vector(shield_point(u1, v1))
        edge = cyl(f"shield_rim_{i}", (p0 + p1) / 2, 0.016, (p1 - p0).length, LEATHER, vertices=8)
        edge.rotation_mode = "QUATERNION"
        edge.rotation_quaternion = (p1 - p0).to_track_quat("Z", "Y")

    def patch(name, u0, u1, v0, v1, nu=8, nv=8):
        pvs, pfs = [], []
        for j in range(nv + 1):
            v = v0 + (v1 - v0) * j / nv
            for i in range(nu + 1):
                u = u0 + (u1 - u0) * i / nu
                pvs.append(shield_point(u, v, lift=0.040))
        for j in range(nv):
            for i in range(nu):
                a = j * (nu + 1) + i
                pfs.append((a, a + 1, a + nu + 2, a + nu + 1))
        smooth(mesh_obj(name, pvs, pfs, CROSS))

    patch("shield_cross_v", -0.042, 0.042, -0.230, 0.290)
    patch("shield_cross_h", -0.165, 0.165, 0.060, 0.144)

build_shield()
# 盾整体移到左前臂前, 略向外张
shield_root = bpy.data.objects.new("shield_root", None)
bpy.context.collection.objects.link(shield_root)
for o in PARTS:
    if o.name.startswith("shield_"):
        o.parent = shield_root
shield_root.location = (0.400, -0.130, 1.075)
shield_root.rotation_euler = (math.radians(6), math.radians(-10), math.radians(-18))

# ---------------------------------------------------------------- 佩剑(左髋, 剑柄朝上)
sword_root = bpy.data.objects.new("sword_root", None)
bpy.context.collection.objects.link(sword_root)
sword_parts = []
scab = cube("scabbard", (0, 0, -0.30), (0.062, 0.030, 0.62), LEATHER, bev=0.008)
sword_parts.append(scab)
sword_parts.append(cube("scabbard_tip", (0, 0, -0.60), (0.050, 0.026, 0.05), BRASS, bev=0.006))
sword_parts.append(cyl("sword_grip", (0, 0, 0.075), 0.021, 0.13, LEATHER, vertices=12))
sword_parts.append(cube("sword_guard", (0, 0, 0.005), (0.185, 0.036, 0.026), HELM, bev=0.006))
sword_parts.append(sphere("sword_pommel", (0, 0, 0.155), (0.032, 0.032, 0.032), BRASS, seg=12, rings=8))
for o in sword_parts:
    o.parent = sword_root
sword_root.location = (0.205, 0.075, 1.020)
sword_root.rotation_euler = (math.radians(-18), math.radians(16), math.radians(-12))

# ---------------------------------------------------------------- 集合与导出
char_col = bpy.data.collections.new("TEMPLAR")
bpy.context.scene.collection.children.link(char_col)
for o in PARTS + [shield_root, sword_root]:
    for c in list(o.users_collection):
        c.objects.unlink(o)
    char_col.objects.link(o)

bpy.ops.object.select_all(action="DESELECT")
for o in PARTS:
    o.select_set(True)

# 统计(应用修改器后的真实面数)
depsgraph = bpy.context.evaluated_depsgraph_get()
tris = 0
for o in PARTS:
    if o.type == "MESH":
        ev = o.evaluated_get(depsgraph)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        tris += len(me.loop_triangles)
        ev.to_mesh_clear()
print(f"[TEMPLAR] 部件数={len(PARTS)} 三角面={tris}")

blend_path = os.path.join(MODELS, "templar.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
glb_path = os.path.join(MODELS, "templar.glb")
bpy.ops.export_scene.gltf(filepath=glb_path, export_format="GLB", use_selection=True,
                          export_apply=True, export_yup=True)
print("[TEMPLAR] exported:", glb_path)

# ---------------------------------------------------------------- 摄影棚与渲染
scene = bpy.context.scene
floor_mat = mat("studio_floor", "24262A", roughness=0.9)
bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.002))
floor = bpy.context.object
floor.name = "studio_floor"
floor.data.materials.append(floor_mat)

world = bpy.data.worlds.new("studio_world")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.055, 0.062, 0.075, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.6

def area(name, loc, energy, color, size, target=(0, 0, 1.0)):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.color = color
    data.size = size
    o = bpy.data.objects.new(name, data)
    scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (Vector(target) - o.location).to_track_quat("-Z", "Y").to_euler()
    return o

area("key", (-2.2, -3.0, 3.4), 420, (1.0, 0.93, 0.84), 3.0)
area("fill", (2.6, -1.6, 1.8), 130, (0.80, 0.86, 1.0), 2.5)
area("rim", (1.2, 2.4, 3.0), 520, (0.72, 0.82, 1.0), 2.0)

cam_data = bpy.data.cameras.new("camera")
cam = bpy.data.objects.new("camera", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
cam_data.type = "ORTHO"
cam_data.ortho_scale = 2.35

scene.render.engine = "CYCLES"
scene.cycles.samples = 40
scene.cycles.use_denoising = True
scene.render.resolution_x = 900
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False

VIEWS = {
    "hero": ((2.6, -4.2, 2.2), (0.05, 0.0, 0.98), 2.25),
    "front": ((0.0, -5.0, 1.05), (0.0, 0.0, 0.95), 2.20),
    "side": ((5.0, 0.0, 1.05), (0.0, 0.0, 0.95), 2.20),
    "back": ((0.0, 5.0, 1.15), (0.0, 0.0, 0.95), 2.20),
}
only = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
for name, (loc, target, scale) in VIEWS.items():
    if only and name not in only:
        continue
    cam.location = loc
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.ortho_scale = scale
    scene.render.filepath = os.path.join(RENDERS, f"templar_{name}.png")
    bpy.ops.render.render(write_still=True)
    print("[TEMPLAR] rendered:", name)

print("[TEMPLAR] DONE")
