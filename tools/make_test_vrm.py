# -*- coding: utf-8 -*-
"""生成一个用于验证 vrm2pmx 的合成 VRM 1.0 测试模型（不依赖任何外部文件）。

这个模型刻意覆盖了转换链路上的所有分支：
  * 完整的人形骨骼（含全部手指骨）与蒙皮（单骨 / 双骨 / 四骨权重都会出现）
  * 两个材质，其中一个带 PNG 贴图，另一个双面
  * 两个形态目标 + VRM 表情预设（blink / aa）+ 一个自定义表情
  * 一条 SpringBone 头发链 + 一个头部碰撞体
  * GLB 容器 + VRMC_vrm / VRMC_springBone / VRMC_materials_mtoon 扩展

用法：
    python tools/make_test_vrm.py [输出路径.vrm]
"""

import json
import math
import os
import struct
import sys
import zlib

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------- PNG

def make_png(width, height, func):
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(bytes(func(x, y)))
    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    return png


# ---------------------------------------------------------------- 骨骼表

def build_bone_table():
    """返回 [(名称, 父名称, 世界坐标)]。"""
    bones = [
        ("Root", None, (0.0, 0.0, 0.0)),
        ("hips", "Root", (0.0, 0.80, 0.0)),
        ("spine", "hips", (0.0, 0.95, 0.0)),
        ("chest", "spine", (0.0, 1.08, 0.0)),
        ("upperChest", "chest", (0.0, 1.20, 0.0)),
        ("neck", "upperChest", (0.0, 1.36, 0.0)),
        ("head", "neck", (0.0, 1.47, 0.0)),
        ("leftEye", "head", (0.032, 1.545, 0.072)),
        ("rightEye", "head", (-0.032, 1.545, 0.072)),
        ("hair_01", "head", (0.0, 1.60, -0.055)),
        ("hair_02", "hair_01", (0.0, 1.50, -0.075)),
        ("hair_03", "hair_02", (0.0, 1.40, -0.095)),
    ]
    for side, sign in (("left", 1.0), ("right", -1.0)):
        bones.extend([
            (side + "Shoulder", "upperChest", (sign * 0.035, 1.32, 0.0)),
            (side + "UpperArm", side + "Shoulder", (sign * 0.13, 1.315, 0.0)),
            (side + "LowerArm", side + "UpperArm", (sign * 0.32, 1.305, 0.0)),
            (side + "Hand", side + "LowerArm", (sign * 0.49, 1.30, 0.0)),
        ])
        wrist_x = sign * 0.49
        # 拇指往前偏一点，其余四指沿 X 继续延伸
        finger_specs = [
            ("ThumbMetacarpal", wrist_x + sign * 0.020, 1.295, 0.025),
            ("ThumbProximal", wrist_x + sign * 0.040, 1.293, 0.035),
            ("ThumbDistal", wrist_x + sign * 0.058, 1.291, 0.045),
        ]
        for name, y_off in (("Index", 0.008), ("Middle", 0.0), ("Ring", -0.008),
                            ("Little", -0.016)):
            base_x = wrist_x + sign * 0.015
            for stage, dx in (("Proximal", 0.018), ("Intermediate", 0.050),
                              ("Distal", 0.078)):
                finger_specs.append((name + stage, wrist_x + sign * (0.015 + dx - 0.015)
                                     + sign * dx * 0.0 + sign * 0.0, 0.0, 0.0))
        # 重新精确生成手指坐标
        bones = [b for b in bones if not any(
            b[0].startswith(side + n) for n in ("Thumb", "Index", "Middle", "Ring",
                                                "Little"))]
        fingers = []
        for name, dx, dy, dz in (
                ("ThumbMetacarpal", 0.020, -0.005, 0.010),
                ("ThumbProximal", 0.042, -0.007, 0.022),
                ("ThumbDistal", 0.062, -0.009, 0.034),
                ("IndexProximal", 0.020, 0.008, 0.001),
                ("IndexIntermediate", 0.048, 0.008, 0.003),
                ("IndexDistal", 0.074, 0.008, 0.005),
                ("MiddleProximal", 0.020, 0.000, 0.001),
                ("MiddleIntermediate", 0.050, 0.000, 0.003),
                ("MiddleDistal", 0.078, 0.000, 0.005),
                ("RingProximal", 0.019, -0.008, 0.001),
                ("RingIntermediate", 0.047, -0.008, 0.003),
                ("RingDistal", 0.073, -0.008, 0.005),
                ("LittleProximal", 0.017, -0.016, 0.001),
                ("LittleIntermediate", 0.042, -0.016, 0.003),
                ("LittleDistal", 0.065, -0.016, 0.005)):
            parent = side + "Hand"
            if "Thumb" in name:
                if name == "ThumbProximal":
                    parent = side + "ThumbMetacarpal"
                elif name == "ThumbDistal":
                    parent = side + "ThumbProximal"
            else:
                base = name.replace("Intermediate", "Proximal")\
                    .replace("Distal", "Intermediate")
                if name.endswith("Intermediate"):
                    parent = side + name.replace("Intermediate", "Proximal")
                elif name.endswith("Distal"):
                    parent = side + name.replace("Distal", "Intermediate")
            fingers.append((side + name, parent,
                            (wrist_x + sign * dx, 1.30 + dy, dz)))
        bones.extend(fingers)
        bones.extend([
            (side + "UpperLeg", "hips", (sign * 0.085, 0.80, 0.0)),
            (side + "LowerLeg", side + "UpperLeg", (sign * 0.085, 0.45, 0.005)),
            (side + "Foot", side + "LowerLeg", (sign * 0.085, 0.075, 0.0)),
            (side + "Toes", side + "Foot", (sign * 0.085, 0.020, 0.115)),
        ])
    return bones


HUMANOID_BONES = [
    "hips", "spine", "chest", "upperChest", "neck", "head",
    "leftEye", "rightEye", "leftShoulder", "leftUpperArm", "leftLowerArm",
    "leftHand", "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToes",
    "rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToes",
]
for _s in ("left", "right"):
    HUMANOID_BONES.extend([
        _s + "ThumbMetacarpal", _s + "ThumbProximal", _s + "ThumbDistal",
        _s + "IndexProximal", _s + "IndexIntermediate", _s + "IndexDistal",
        _s + "MiddleProximal", _s + "MiddleIntermediate", _s + "MiddleDistal",
        _s + "RingProximal", _s + "RingIntermediate", _s + "RingDistal",
        _s + "LittleProximal", _s + "LittleIntermediate", _s + "LittleDistal",
    ])

# 生成盒子的骨骼 -> 厚度 / 材质
SKIN_BONES = ("hips", "spine", "chest", "upperChest", "neck", "head",
              "leftShoulder", "rightShoulder")
CLOTH_PREFIX = ("leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm",
                "rightLowerArm", "rightHand", "leftUpperLeg", "leftLowerLeg",
                "leftFoot", "leftToes", "rightUpperLeg", "rightLowerLeg",
                "rightFoot", "rightToes", "hair_")

THICKNESS = {
    "head": 0.075, "neck": 0.028, "hips": 0.075, "spine": 0.075,
    "chest": 0.08, "upperChest": 0.08, "Root": 0.0,
}


def thickness_of(name):
    if name in THICKNESS:
        return THICKNESS[name]
    if name.startswith("hair_"):
        return 0.03
    if "Shoulder" in name:
        return 0.032
    if any(name.startswith(p) and ("Arm" in name or "Hand" == name[-4:])
           for p in ("left", "right")):
        return 0.028
    if "UpperArm" in name or "LowerArm" in name or name.endswith("Hand"):
        return 0.028
    if "Leg" in name or "Foot" in name or "Toes" in name:
        return 0.038
    if any(k in name for k in ("Thumb", "Index", "Middle", "Ring", "Little")):
        return 0.007
    return 0.04


def material_of(name):
    if name in SKIN_BONES or name.startswith("hair_") is False and name in SKIN_BONES:
        return 0
    if name in SKIN_BONES:
        return 0
    if any(name.startswith(p) for p in CLOTH_PREFIX):
        return 1
    return 0


class GlbBuilder(object):
    def __init__(self):
        self.chunks = []
        self.views = []
        self.accessors = []
        self.buffer = bytearray()

    def add_view(self, data, target=None):
        while len(self.buffer) % 4:
            self.buffer.append(0)
        offset = len(self.buffer)
        self.buffer.extend(data)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        self.views.append(view)
        return len(self.views) - 1

    def add_accessor(self, view, component_type, count, type_name, minmax=None):
        acc = {"bufferView": view, "componentType": component_type,
               "count": count, "type": type_name}
        if minmax:
            acc["min"] = minmax[0]
            acc["max"] = minmax[1]
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def add_float_accessor(self, values, components, type_name, target=None,
                           with_bounds=False):
        data = struct.pack("<%df" % len(values), *values)
        view = self.add_view(data, target)
        bounds = None
        if with_bounds:
            mins = [min(values[i::components]) for i in range(components)]
            maxs = [max(values[i::components]) for i in range(components)]
            bounds = (mins, maxs)
        return self.add_accessor(view, 5126, len(values) // components, type_name,
                                 bounds)

    def add_uint_accessor(self, values, components, type_name, target=None):
        data = struct.pack("<%dI" % len(values), *values)
        view = self.add_view(data, target)
        return self.add_accessor(view, 5125, len(values) // components, type_name)


def build(path):
    bones = build_bone_table()
    name_to_index = {name: i for i, (name, _p, _pos) in enumerate(bones)}
    positions = {name: pos for name, _p, pos in bones}

    nodes = []
    for name, parent, pos in bones:
        node = {"name": name, "translation": [0.0, 0.0, 0.0]}
        if parent:
            pp = positions[parent]
            node["translation"] = [pos[0] - pp[0], pos[1] - pp[1], pos[2] - pp[2]]
        else:
            node["translation"] = list(pos)
        nodes.append(node)
    for name, parent, _pos in bones:
        if parent:
            nodes[name_to_index[parent]].setdefault("children", []).append(
                name_to_index[name])

    # 网格节点
    mesh_node = len(nodes)
    nodes.append({"name": "Body", "mesh": 0, "skin": 0})

    children = {}
    for name, parent, _pos in bones:
        if parent:
            children.setdefault(parent, []).append(name)

    order = [name for name, _p, _pos in bones]
    per_bone_verts = {}
    per_bone_tris = {}
    per_bone_mat = {}
    for name in order:
        if name == "Root":
            continue
        p = positions[name]
        kids = children.get(name, [])
        if kids:
            q = positions[kids[0]]
        else:
            parent = None
            for n2, p2, _pos2 in bones:
                if n2 in children and name in children[n2]:
                    parent = n2
                    break
            pp = positions[parent] if parent else p
            direction = (p[0] - pp[0], p[1] - pp[1], p[2] - pp[2])
            length = math.sqrt(sum(d * d for d in direction)) or 0.02
            scale = 0.02 / length
            q = (p[0] + direction[0] * scale, p[1] + direction[1] * scale,
                 p[2] + direction[2] * scale)
        per_bone_verts[name] = (p, q)
        t = thickness_of(name)
        per_bone_tris[name] = t
        per_bone_mat[name] = material_of(name)

    # 每个骨骼一个盒子的六个面，每面 4 个独立顶点
    face_defs = [
        ((0, 1, 1), (1, 1, 1), (1, 1, -1), (0, 1, -1)),
        ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
        ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),
        ((1, 0, 1), (1, 0, 0), (1, 1, 0), (1, 1, 1)),
        ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),
        ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)),
    ]
    face_normals = [(0, 1, 0), (0, -1, 0), (-1, 0, 0), (1, 0, 0), (0, 0, 1),
                    (0, 0, -1)]
    face_uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

    prim_data = {0: {"pos": [], "nrm": [], "uv": [], "joints": [], "weights": [],
                     "idx": [], "bone": []},
                 1: {"pos": [], "nrm": [], "uv": [], "joints": [], "weights": [],
                     "idx": [], "bone": []}}
    eye_vertex_positions = []
    head_front_vertices = []

    for name in order:
        if name == "Root":
            continue
        p, q = per_bone_verts[name]
        t = per_bone_tris[name]
        mat = per_bone_mat[name]
        bucket = prim_data[mat]
        lo = [min(p[i], q[i]) - (0.0 if i == 1 and abs(q[1] - p[1]) > 1e-6 else t)
              for i in range(3)]
        hi = [max(p[i], q[i]) + (0.0 if i == 1 and abs(q[1] - p[1]) > 1e-6 else t)
              for i in range(3)]
        # 让盒子在三个轴上都至少有厚度，避免退化成面片
        for i in range(3):
            if hi[i] - lo[i] < t:
                c = (hi[i] + lo[i]) / 2
                lo[i] = c - t / 2
                hi[i] = c + t / 2
        bone_index = name_to_index[name]
        base = len(bucket["pos"]) // 3
        for fi, face in enumerate(face_defs):
            for ci, corner in enumerate(face):
                x = lo[0] if corner[0] <= 0 else hi[0]
                y = lo[1] if corner[1] <= 0 else hi[1]
                z = lo[2] if corner[2] <= 0 else hi[2]
                bucket["pos"].extend((x, y, z))
                bucket["nrm"].extend(face_normals[fi])
                bucket["uv"].extend(face_uv[ci])
                bucket["joints"].extend((bone_index, 0, 0, 0))
                bucket["weights"].extend((1.0, 0.0, 0.0, 0.0))
                if name in ("head", "leftEye", "rightEye"):
                    eye_vertex_positions.append((len(bucket["pos"]) // 3 - 1, mat, x, y, z))
                if name == "head":
                    head_front_vertices.append((1, mat, len(bucket["pos"]) // 3 - 1,
                                               x, y, z))
            a, b, c, d = base + fi * 4, base + fi * 4 + 1, base + fi * 4 + 2, \
                base + fi * 4 + 3
            bucket["idx"].extend((a, b, c, a, c, d))

    # 追加一个四骨权重的补丁，专门验证 BDEF4
    patch = prim_data[1]
    patch_base = len(patch["pos"]) // 3
    quad_bones = [name_to_index["leftUpperLeg"], name_to_index["rightUpperLeg"],
                  name_to_index["hips"], name_to_index["spine"]]
    quad_weights = (0.25, 0.25, 0.25, 0.25)
    quad = [(0.055, 0.74, 0.10), (0.115, 0.74, 0.10), (0.115, 0.74, 0.14),
            (0.055, 0.74, 0.14)]
    for i, (x, y, z) in enumerate(quad):
        patch["pos"].extend((x, y, z))
        patch["nrm"].extend((0.0, 1.0, 0.0))
        patch["uv"].extend(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))[i])
        patch["joints"].extend(quad_bones)
        patch["weights"].extend(quad_weights)
    patch["idx"].extend((patch_base, patch_base + 2, patch_base + 1,
                         patch_base, patch_base + 3, patch_base + 2))
    # 再来一段双骨权重
    two_bones = [name_to_index["leftFoot"], name_to_index["leftToes"]]
    twin = [(0.055, 0.30, 0.10), (0.115, 0.30, 0.10), (0.115, 0.30, 0.14),
            (0.055, 0.30, 0.14)]
    twin_base = len(patch["pos"]) // 3
    for i, (x, y, z) in enumerate(twin):
        patch["pos"].extend((x, y, z))
        patch["nrm"].extend((0.0, -1.0, 0.0))
        patch["uv"].extend(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))[i])
        patch["joints"].extend((two_bones[0], two_bones[1], 0, 0))
        patch["weights"].extend((0.5, 0.5, 0.0, 0.0))
    patch["idx"].extend((twin_base, twin_base + 1, twin_base + 2,
                         twin_base, twin_base + 2, twin_base + 3))

    glb = GlbBuilder()
    texture_png = make_png(32, 32, lambda x, y: (
        (40 + x * 6) % 256, (90 + y * 4) % 256, 210))

    accessors = {}
    primitives = []
    target_deltas = {0: [], 1: []}     # material -> [target0 accessor, target1 accessor]
    for mat in (0, 1):
        bucket = prim_data[mat]
        count = len(bucket["pos"]) // 3
        pos_acc = glb.add_float_accessor(bucket["pos"], 3, "VEC3", 34962, True)
        nrm_acc = glb.add_float_accessor(bucket["nrm"], 3, "VEC3", 34962)
        uv_acc = glb.add_float_accessor(bucket["uv"], 2, "VEC2", 34962)
        joint_acc = glb.add_uint_accessor(bucket["joints"], 4, "VEC4", 34962)
        weight_acc = glb.add_float_accessor(bucket["weights"], 4, "VEC4", 34962)
        index_acc = glb.add_uint_accessor(bucket["idx"], 1, "SCALAR", 34963)

        targets = []
        for which in (0, 1):
            deltas = [0.0] * (count * 3)
            for entry in eye_vertex_positions:
                vi, m, x, y, z = entry
                if m != mat:
                    continue
                if which == 0 and abs(y - 1.545) < 0.05 and z > 0.05:
                    deltas[vi * 3 + 1] = -0.004
                if which == 1 and abs(y - 1.50) < 0.09 and z > 0.03:
                    deltas[vi * 3 + 1] = -0.006
                    deltas[vi * 3 + 2] = 0.004
            if mat == 1 and which == 1:
                deltas[(patch_base) * 3 + 1] = -0.01
            acc = glb.add_float_accessor(deltas, 3, "VEC3")
            targets.append({"POSITION": acc})
        primitives.append({
            "attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc,
                           "TEXCOORD_0": uv_acc, "JOINTS_0": joint_acc,
                           "WEIGHTS_0": weight_acc},
            "indices": index_acc,
            "material": mat,
            "targets": targets,
        })
        accessors[mat] = pos_acc

    # 贴图：直接写进 buffer
    tex_view = glb.add_view(texture_png)
    images = [{"bufferView": tex_view, "mimeType": "image/png", "name": "body_tex"}]
    textures = [{"sampler": 0, "source": 0}]
    samplers = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497,
                 "wrapT": 10497}]

    # 逆绑定矩阵
    ibm = []
    for name, _p, _pos in bones:
        px, py, pz = positions[name]
        ibm.extend((1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -px, -py, -pz, 1))
    ibm_view = glb.add_view(struct.pack("<%df" % len(ibm), *ibm))
    ibm_acc = glb.add_accessor(ibm_view, 5126, len(bones), "MAT4")

    materials = [
        {"name": "skin",
         "pbrMetallicRoughness": {
             "baseColorTexture": {"index": 0},
             "baseColorFactor": [1.0, 0.93, 0.88, 1.0],
             "metallicFactor": 0.0, "roughnessFactor": 0.9},
         "doubleSided": False,
         "extensions": {"VRMC_materials_mtoon": {
             "specVersion": "1.0", "shadeColorFactor": [0.72, 0.62, 0.60],
             "shadingToony": 0.9, "outlineWidth": 0.004,
             "outlineColorFactor": [0.1, 0.05, 0.05, 1.0]}}},
        {"name": "cloth",
         "pbrMetallicRoughness": {
             "baseColorFactor": [0.28, 0.40, 0.85, 1.0],
             "metallicFactor": 0.0, "roughnessFactor": 0.8},
         "doubleSided": True},
    ]

    extensions = {
        "VRMC_vrm": {
            "specVersion": "1.0",
            "meta": {
                "name": "vrm2pmx \u6d4b\u8bd5\u6a21\u578b",
                "version": "1.0",
                "authors": ["vrm2pmx"],
                "licenseUrl": "https://example.invalid/test-license",
                "avatarPermission": "everyone",
                "commercialUsage": "personalNonProfit",
                "creditNotation": "required",
                "allowRedistribution": False,
                "modification": "prohibited",
            },
            "humanoid": {"humanBones": {
                name: {"node": name_to_index[name]} for name in HUMANOID_BONES
                if name in name_to_index}},
            "expressions": {
                "preset": {
                    "blink": {"morphTargetBinds": [
                        {"node": mesh_node, "index": 0, "weight": 1.0}]},
                    "aa": {"morphTargetBinds": [
                        {"node": mesh_node, "index": 1, "weight": 1.0}]},
                    "happy": {"morphTargetBinds": [
                        {"node": mesh_node, "index": 1, "weight": 0.4}]},
                },
                "custom": {
                    "mySmile": {"morphTargetBinds": [
                        {"node": mesh_node, "index": 1, "weight": 0.8}],
                        "isBinary": False},
                },
            },
        },
        "VRMC_springBone": {
            "specVersion": "1.0",
            "colliders": [
                {"node": name_to_index["head"],
                 "shape": {"sphere": {"offset": [0.0, 0.02, -0.02],
                                      "radius": 0.075}}},
                {"node": name_to_index["upperChest"],
                 "shape": {"capsule": {"offset": [0.0, 0.02, -0.03],
                                       "radius": 0.07,
                                       "tail": [0.0, -0.20, -0.03]}}},
            ],
            "colliderGroups": [
                {"name": "head", "colliders": [0]},
                {"name": "chest", "colliders": [1]},
            ],
            "springs": [{
                "name": "hair",
                "joints": [
                    {"node": name_to_index["hair_01"], "hitRadius": 0.028,
                     "stiffness": 0.5, "dragForce": 0.4, "gravityPower": 1.0,
                     "gravityDir": [0.0, -1.0, 0.0]},
                    {"node": name_to_index["hair_02"], "hitRadius": 0.026,
                     "stiffness": 0.35, "dragForce": 0.4, "gravityPower": 1.0,
                     "gravityDir": [0.0, -1.0, 0.0]},
                    {"node": name_to_index["hair_03"], "hitRadius": 0.024,
                     "stiffness": 0.2, "dragForce": 0.4, "gravityPower": 1.0,
                     "gravityDir": [0.0, -1.0, 0.0]},
                ],
                "colliderGroups": [0, 1],
            }],
        },
    }

    gltf = {
        "asset": {"version": "2.0", "generator": "vrm2pmx test fixture"},
        "scene": 0,
        "scenes": [{"name": "Scene", "nodes": [0, mesh_node]}],
        "nodes": nodes,
        "meshes": [{"name": "Body", "primitives": primitives,
                    "weights": [0.0, 0.0]}],
        "skins": [{"name": "Armature", "joints": [name_to_index[n] for n, _p, _q
                                                  in bones],
                   "inverseBindMatrices": ibm_acc,
                   "skeleton": name_to_index["Root"]}],
        "materials": materials,
        "textures": textures,
        "images": images,
        "samplers": samplers,
        "accessors": glb.accessors,
        "bufferViews": glb.views,
        "buffers": [{"byteLength": len(glb.buffer)}],
        "extensionsUsed": ["VRMC_vrm", "VRMC_springBone", "VRMC_materials_mtoon"],
        "extensions": extensions,
    }

    json_bytes = json.dumps(gltf, ensure_ascii=False).encode("utf-8")
    while len(json_bytes) % 4:
        json_bytes += b" "
    bin_data = bytes(glb.buffer)
    while len(bin_data) % 4:
        bin_data += b"\x00"

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    out = bytearray()
    out.extend(struct.pack("<III", 0x46546C67, 2, total))
    out.extend(struct.pack("<II", len(json_bytes), 0x4E4F534A))
    out.extend(json_bytes)
    out.extend(struct.pack("<II", len(bin_data), 0x004E4942))
    out.extend(bin_data)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return path, len(out), len(glb.accessors), sum(
        len(p["pos"]) // 3 for p in prim_data.values())


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "samples", "\u6d4b\u8bd5\u6a21\u578b.vrm")
    path = sys.argv[1] if len(sys.argv) > 1 else default
    path, size, acc, verts = build(path)
    print("已生成测试 VRM：%s" % path)
    print("  文件大小: %d 字节 / accessor %d 个 / 顶点 %d 个" % (size, acc, verts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
