# -*- coding: utf-8 -*-
"""VRM 语义层：把 VRM 0.x 与 VRM 1.0 统一成同一套结构，供转换器使用。

统一后的结构：
    VrmModel.version            0 或 1
    VrmModel.meta               名称/作者/授权等
    VrmModel.humanoid_bones     {规范骨骼名: 节点索引}（0.x 的拇指命名已对齐到 1.0）
    VrmModel.expressions        [VrmExpression]
    VrmModel.springs            [VrmSpring]（含 joint 链与 colliderGroup 引用）
    VrmModel.colliders          [VrmCollider]
    VrmModel.collider_groups    [[collider 索引]]
    VrmModel.look_at            注视设置
    VrmModel.first_person       第三人称/第一人称网格标注
    VrmModel.mtoon_materials    {材质索引: MToon 参数}

两个版本的关键差异（本模块负责抹平）：
  * humanoid 结构：0.x 是 {bone,node} 数组；1.0 是 {bone:{node}} 字典
  * 拇指骨骼命名：0.x 的 ThumbProximal/Intermediate/Distal 对应 1.0 的
    ThumbMetacarpal/Proximal/Distal，此处统一成 1.0 命名
  * 表情：0.x blendShapeGroups(binds)；1.0 expressions.preset/custom(morphTargetBinds)
  * 物理：0.x secondaryAnimation（boneGroups 每条自带参数）；1.0 VRMC_springBone
    （每个 joint 自带参数）
  * 表情预设名：0.x 的 joy/sorrow/fun/blink_l/blink_r 等映射到 1.0 的
    happy/sad/relaxed/blinkLeft/blinkRight
"""

import os

__all__ = ["VrmModel", "VrmExpression", "VrmSpring", "VrmJoint", "VrmCollider",
           "read_vrm", "VrmError"]


class VrmError(Exception):
    pass


# VRM 0.x 预设名 -> VRM 1.0 规范名
PRESET_0X_TO_1X = {
    "neutral": "neutral",
    "a": "aa", "i": "ih", "u": "ou", "e": "ee", "o": "oh",
    "blink": "blink", "blink_l": "blinkLeft", "blink_r": "blinkRight",
    "joy": "happy", "angry": "angry", "sorrow": "sad", "fun": "relaxed",
    "lookup": "lookUp", "lookdown": "lookDown",
    "lookleft": "lookLeft", "lookright": "lookRight",
    "unknown": "",
}

# VRM 0.x 拇指命名 -> VRM 1.0 命名
BONE_0X_RENAME = {
    "leftThumbProximal": "leftThumbMetacarpal",
    "leftThumbIntermediate": "leftThumbProximal",
    "rightThumbProximal": "rightThumbMetacarpal",
    "rightThumbIntermediate": "rightThumbProximal",
}

# VRM 1.0 规范骨骼名（转换器只认这一套）
STANDARD_BONES = [
    "hips", "spine", "chest", "upperChest", "neck", "head",
    "leftEye", "rightEye",
    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftThumbMetacarpal", "leftThumbProximal", "leftThumbDistal",
    "leftIndexProximal", "leftIndexIntermediate", "leftIndexDistal",
    "leftMiddleProximal", "leftMiddleIntermediate", "leftMiddleDistal",
    "leftRingProximal", "leftRingIntermediate", "leftRingDistal",
    "leftLittleProximal", "leftLittleIntermediate", "leftLittleDistal",
    "rightThumbMetacarpal", "rightThumbProximal", "rightThumbDistal",
    "rightIndexProximal", "rightIndexIntermediate", "rightIndexDistal",
    "rightMiddleProximal", "rightMiddleIntermediate", "rightMiddleDistal",
    "rightRingProximal", "rightRingIntermediate", "rightRingDistal",
    "rightLittleProximal", "rightLittleIntermediate", "rightLittleDistal",
    "leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToes",
    "rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToes",
]


class VrmExpression(object):
    """统一后的表情：一组 morph target 绑定 + 材质绑定。"""

    __slots__ = ("name", "preset", "is_binary", "morph_binds", "material_binds")

    def __init__(self, name, preset="", is_binary=False):
        self.name = name
        self.preset = preset
        self.is_binary = is_binary
        # (节点索引, target 序号, 权重)
        self.morph_binds = []
        # (材质索引, 属性名, 目标值, 原始值) —— 属性名统一成 baseColor / shadeColor 等
        self.material_binds = []

    def __repr__(self):
        return "<VrmExpression %r preset=%r morphs=%d materials=%d>" % (
            self.name, self.preset, len(self.morph_binds), len(self.material_binds))


class VrmJoint(object):
    __slots__ = ("node", "hit_radius", "stiffness", "drag_force",
                 "gravity_power", "gravity_dir")

    def __init__(self, node, hit_radius=0.0, stiffness=0.0, drag_force=0.0,
                 gravity_power=0.0, gravity_dir=(0.0, -1.0, 0.0)):
        self.node = node
        self.hit_radius = hit_radius
        self.stiffness = stiffness
        self.drag_force = drag_force
        self.gravity_power = gravity_power
        self.gravity_dir = gravity_dir


class VrmSpring(object):
    __slots__ = ("name", "joints", "collider_groups")

    def __init__(self, name="", joints=None, collider_groups=None):
        self.name = name
        self.joints = list(joints) if joints else []
        self.collider_groups = list(collider_groups) if collider_groups else []

    def __repr__(self):
        return "<VrmSpring %r joints=%d colliderGroups=%s>" % (
            self.name, len(self.joints), self.collider_groups)


class VrmCollider(object):
    __slots__ = ("node", "shape", "offset", "radius", "tail")

    def __init__(self, node, shape="sphere", offset=(0.0, 0.0, 0.0), radius=0.0,
                 tail=(0.0, 0.0, 0.0)):
        self.node = node
        self.shape = shape          # "sphere" | "capsule"
        self.offset = offset
        self.radius = radius
        self.tail = tail


class VrmModel(object):
    def __init__(self, doc):
        self.doc = doc
        self.version = 1
        self.meta = {}
        self.humanoid_bones = {}
        self.expressions = []
        self.springs = []
        self.colliders = []
        self.collider_groups = []
        self.look_at = {}
        self.first_person = {}
        self.mtoon_materials = {}
        self.material_properties = []
        self.warnings = []

    def __repr__(self):
        return ("<VrmModel VRM%s 骨骼=%d 表情=%d 物理链=%d 碰撞体=%d 材质=%d>"
                % ("1.0" if self.version == 1 else "0.x", len(self.humanoid_bones),
                   len(self.expressions), len(self.springs), len(self.colliders),
                   len(self.mtoon_materials)))

    def node(self, index):
        """节点索引 -> 该节点的世界坐标（源坐标系）。"""
        return self.doc.world_translation(index)


# ------------------------------------------------------------------ 解析


def _parse_meta_0x(meta):
    return {
        "name": meta.get("title", ""),
        "version": meta.get("version", ""),
        "authors": [meta.get("author", "")] if meta.get("author") else [],
        "contact": meta.get("contactInformation", ""),
        "references": [meta.get("reference", "")] if meta.get("reference") else [],
        "license": meta.get("licenseName", ""),
        "avatar_permission": meta.get("allowedUserName", ""),
        "commercial": meta.get("commercialUssageName", ""),
        "raw": meta,
    }


def _parse_meta_1x(meta):
    return {
        "name": meta.get("name", ""),
        "version": meta.get("version", ""),
        "authors": list(meta.get("authors") or []),
        "contact": meta.get("contactInformation", ""),
        "references": list(meta.get("references") or []),
        "license": meta.get("licenseUrl", ""),
        "avatar_permission": meta.get("avatarPermission", ""),
        "commercial": meta.get("commercialUsage", ""),
        "copyright": meta.get("copyrightInformation", ""),
        "raw": meta,
    }


def _norm_preset(name):
    name = (name or "").strip()
    lowered = name.lower()
    if lowered in PRESET_0X_TO_1X:
        return PRESET_0X_TO_1X[lowered]
    for standard in ("happy", "angry", "sad", "relaxed", "surprised", "aa", "ih",
                     "ou", "ee", "oh", "blink", "blinkLeft", "blinkRight",
                     "lookUp", "lookDown", "lookLeft", "lookRight", "neutral"):
        if lowered == standard.lower():
            return standard
    return ""


def parse_vrm(doc):
    """把 GltfDocument 解析成统一的 VrmModel。"""
    exts = doc.json.get("extensions") or {}
    vrm0 = exts.get("VRM")
    vrm1 = exts.get("VRMC_vrm")
    if not vrm0 and not vrm1:
        raise VrmError("该文件不是 VRM：既没有 VRM 扩展（0.x）也没有 VRMC_vrm 扩展（1.0）")

    model = VrmModel(doc)
    if vrm1:
        model.version = 1
        model.meta = _parse_meta_1x(vrm1.get("meta") or {})
        hb = (vrm1.get("humanoid") or {}).get("humanBones") or {}
        for name, info in hb.items():
            node = (info or {}).get("node")
            if isinstance(node, int):
                model.humanoid_bones[name] = node
        _parse_expressions_1x(model, vrm1)
        _parse_lookat_1x(model, vrm1)
        model.first_person = vrm1.get("firstPerson") or {}
    else:
        model.version = 0
        model.meta = _parse_meta_0x(vrm0.get("meta") or {})
        for item in (vrm0.get("humanoid") or {}).get("humanBones") or []:
            name = item.get("bone")
            node = item.get("node")
            if name is None or not isinstance(node, int):
                continue
            model.humanoid_bones[BONE_0X_RENAME.get(name, name)] = node
        _parse_expressions_0x(model, vrm0)
        _parse_lookat_0x(model, vrm0)
        model.first_person = vrm0.get("firstPerson") or {}
        model.material_properties = vrm0.get("materialProperties") or []

    _parse_spring_bone(model, exts)
    _parse_mtoon(model, exts)
    _validate(model)
    return model


def _parse_expressions_1x(model, vrm1):
    expressions = (vrm1.get("expressions") or {})
    for bucket, is_preset in (("preset", True), ("custom", False)):
        for name, value in (expressions.get(bucket) or {}).items():
            value = value or {}
            expr = VrmExpression(name, _norm_preset(name) if is_preset else "",
                                 bool(value.get("isBinary")))
            for bind in value.get("morphTargetBinds") or []:
                node = bind.get("node")
                index = bind.get("index")
                weight = bind.get("weight", 1.0)
                if isinstance(node, int) and isinstance(index, int):
                    expr.morph_binds.append((node, index, float(weight)))
            for bind in value.get("materialColorBinds") or []:
                mat = bind.get("material")
                target = bind.get("targetValue") or []
                if isinstance(mat, int) and len(target) >= 4:
                    expr.material_binds.append(
                        (mat, bind.get("type", "color"), tuple(float(v) for v in target[:4]),
                         tuple(float(v) for v in (bind.get("targetValue") or [])[:4])))
            model.expressions.append(expr)


def _parse_expressions_0x(model, vrm0):
    groups = (vrm0.get("blendShapeMaster") or {}).get("blendShapeGroups") or []
    for group in groups:
        preset = _norm_preset(group.get("presetName"))
        name = group.get("name") or preset or "expression"
        expr = VrmExpression(name, preset)
        for bind in group.get("binds") or []:
            mesh = bind.get("mesh")
            index = bind.get("index")
            weight = bind.get("weight", 100.0)
            material_name = bind.get("materialName")
            property_name = bind.get("propertyName")
            if material_name:
                expr.material_binds.append(
                    (material_name, property_name or "",
                     bind.get("targetValue"), None))
            elif isinstance(mesh, int) and isinstance(index, int):
                # 0.x 里 mesh 是 mesh 索引、weight 是百分比
                expr.morph_binds.append((mesh, index, float(weight) / 100.0))
        # 0.x 的 materialValues：颜色类的目标值在这里
        for mv in group.get("materialValues") or []:
            name = mv.get("materialName")
            if not name:
                continue
            expr.material_binds.append(
                (name, mv.get("propertyName") or "", mv.get("targetValue"), None))
        model.expressions.append(expr)


def _parse_lookat_1x(model, vrm1):
    look = vrm1.get("lookAt") or {}
    out = {"type": look.get("type", ""),
           "offset": look.get("offsetFromHeadBone") or (0.0, 0.0, 0.0)}
    for key in ("rangeMapHorizontalInner", "rangeMapHorizontalOuter",
                "rangeMapVerticalDown", "rangeMapVerticalUp"):
        v = look.get(key) or {}
        out[key] = (v.get("inputMaxValue"), v.get("outputScale"))
    model.look_at = out


def _parse_lookat_0x(model, vrm0):
    fp = vrm0.get("firstPerson") or {}
    look = fp.get("lookAt") or {}
    out = {"type": look.get("type", ""),
           "offset": look.get("offsetFromHeadBone") or (0.0, 0.0, 0.0)}
    for key in ("horizontalInner", "horizontalOuter", "verticalDown", "verticalUp"):
        v = look.get(key) or {}
        out[key] = (v.get("inputMaxValue"), v.get("outputScale"))
    model.look_at = out


def _vec3(value, default=(0.0, 0.0, 0.0)):
    if value is None:
        return default
    if isinstance(value, dict):
        return (float(value.get("x", default[0])), float(value.get("y", default[1])),
                float(value.get("z", default[2])))
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    return default


def _parse_spring_bone(model, exts):
    # ---- VRM 1.0 ----
    sb = exts.get("VRMC_springBone")
    if sb:
        colliders = []
        for item in sb.get("colliders") or []:
            node = item.get("node")
            shape = item.get("shape") or {}
            if "sphere" in shape:
                s = shape["sphere"] or {}
                colliders.append(VrmCollider(
                    node, "sphere", _vec3(s.get("offset")),
                    float(s.get("radius", 0.0))))
            elif "capsule" in shape:
                c = shape["capsule"] or {}
                colliders.append(VrmCollider(
                    node, "capsule", _vec3(c.get("offset")),
                    float(c.get("radius", 0.0)), _vec3(c.get("tail"))))
            else:
                model.warnings.append("SpringBone collider[%s] 形状未知" % item.get("node"))
        model.colliders = colliders
        model.collider_groups = [
            list(g.get("colliders") or []) for g in (sb.get("colliderGroups") or [])
        ]
        for item in sb.get("springs") or []:
            spring = VrmSpring(item.get("name") or "",
                               collider_groups=list(item.get("colliderGroups") or []))
            for j in item.get("joints") or []:
                spring.joints.append(VrmJoint(
                    j.get("node"),
                    float(j.get("hitRadius", 0.0)),
                    float(j.get("stiffness", 0.0)),
                    float(j.get("dragForce", 0.0)),
                    float(j.get("gravityPower", 0.0)),
                    _vec3(j.get("gravityDir"), (0.0, -1.0, 0.0))))
            model.springs.append(spring)
        return

    # ---- VRM 0.x ----
    sa = (exts.get("VRM") or {}).get("secondaryAnimation") or {}
    colliders = []
    for group in sa.get("colliderGroups") or []:
        node = group.get("node")
        for c in group.get("colliders") or []:
            colliders.append(VrmCollider(node, "sphere", _vec3(c.get("offset")),
                                         float(c.get("radius", 0.0))))
    model.colliders = colliders
    groups = sa.get("colliderGroups") or []
    # 0.x 的 colliderGroup 是分组后的，按组收集扁平索引
    flat = []
    index = 0
    for group in groups:
        n = len(group.get("colliders") or [])
        flat.append(list(range(index, index + n)))
        index += n
    model.collider_groups = flat

    for g in sa.get("boneGroups") or []:
        spring = VrmSpring(g.get("comment") or "",
                           collider_groups=list(g.get("colliderGroups") or []))
        stiffness = float(g.get("stiffiness", 0.0))
        drag = float(g.get("dragForce", 0.0))
        gravity = float(g.get("gravityPower", 0.0))
        gdir = _vec3(g.get("gravityDir"), (0.0, -1.0, 0.0))
        radius = float(g.get("hitRadius", 0.0))
        for node in g.get("bones") or []:
            spring.joints.append(VrmJoint(node, radius, stiffness, drag, gravity, gdir))
        if spring.joints:
            model.springs.append(spring)


MTOON_KEY_MAP = {
    # VRM 1.0 名称 -> 统一名称
    "litColor": "litColor", "shadeColor": "shadeColor",
    "shadingToony": "shadingToony", "shadingShift": "shadingShift",
    "outlineWidth": "outlineWidth", "outlineColor": "outlineColor",
}


def _parse_mtoon(model, exts):
    mats = model.doc.json.get("materials") or []
    for i, mat in enumerate(mats):
        me = (mat.get("extensions") or {})
        if "VRMC_materials_mtoon" in me:
            model.mtoon_materials[i] = dict(me["VRMC_materials_mtoon"])
    # VRM 0.x 的材质属性按材质名索引
    if model.material_properties:
        by_name = {}
        for entry in model.material_properties:
            by_name[entry.get("name")] = entry
        for i, mat in enumerate(mats):
            entry = by_name.get(mat.get("name"))
            if entry:
                model.mtoon_materials.setdefault(i, {}).update(entry)


def _validate(model):
    """给出可读的问题提示，但不阻断转换。"""
    required = ["hips", "spine", "head", "neck",
                "leftUpperArm", "leftLowerArm", "leftHand",
                "rightUpperArm", "rightLowerArm", "rightHand",
                "leftUpperLeg", "leftLowerLeg", "leftFoot",
                "rightUpperLeg", "rightLowerLeg", "rightFoot"]
    missing = [b for b in required if b not in model.humanoid_bones]
    if missing:
        model.warnings.append(
            "缺少 VRM 必备人形骨骼：%s。转换仍会继续，但骨骼映射会退化。" % ", ".join(missing))
    if "hips" not in model.humanoid_bones:
        model.warnings.append("缺少 hips，无法确定模型根节点，转换结果可能错位。")


def read_vrm(path):
    from . import gltf as G
    doc = G.read_gltf(path)
    return parse_vrm(doc)
