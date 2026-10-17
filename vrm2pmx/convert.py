# -*- coding: utf-8 -*-
"""转换总装：VRM 文件 -> PMX 文件。"""

import os
import time

from . import gltf as G
from . import materials as MAT
from . import mesh as MESH
from . import mmd_bones as MB
from . import morphs as MORPHS
from . import physics as PHYS
from . import pmx_model as P
from . import vrm as VRM
from .transform import Transform, DEFAULT_UNIT_SCALE

__all__ = ["ConversionOptions", "ConversionResult", "convert", "convert_file"]


class ConversionOptions(object):
    """转换参数。"""

    def __init__(self, unit_scale=DEFAULT_UNIT_SCALE, ground_align=False,
                 edge=True, edge_size=1.0, auto_physics=True, flip_v=False,
                 pmx_version=2.0, text_encoding=P.TEXT_UTF16,
                 physics=True, morphs=True, keep_extra_bones=True,
                 model_name=None):
        self.unit_scale = float(unit_scale)
        self.ground_align = bool(ground_align)
        self.edge = bool(edge)
        self.edge_size = float(edge_size)
        self.auto_physics = bool(auto_physics)
        self.flip_v = bool(flip_v)
        self.pmx_version = float(pmx_version)
        self.text_encoding = text_encoding
        self.physics = bool(physics)
        self.morphs = bool(morphs)
        self.keep_extra_bones = bool(keep_extra_bones)
        self.model_name = model_name

    def to_dict(self):
        return dict(self.__dict__)

    def __repr__(self):
        return "<ConversionOptions %s>" % self.to_dict()


class ConversionResult(object):
    def __init__(self):
        self.output = ""
        self.textures = []
        self.warnings = []
        self.stats = {}
        self.elapsed = 0.0

    def summary(self):
        s = self.stats
        return ("顶点 %s / 三角 %s / 材质 %s / 骨骼 %s / 表情 %s / "
                "刚体 %s / 关节 %s / 贴图 %s" % (
                    s.get("vertices"), s.get("triangles"), s.get("materials"),
                    s.get("bones"), s.get("morphs"), s.get("rigidbodies"),
                    s.get("joints"), s.get("textures")))


def convert(vrm_path, out_dir=None, options=None, progress=None):
    """把 VRM 转成 PMX，返回 ConversionResult。"""
    started = time.time()
    options = options or ConversionOptions()
    result = ConversionResult()

    def log(msg):
        if progress:
            progress(msg)

    def check():
        pass

    doc = G.read_gltf(vrm_path)
    check()
    log("解析 glTF/GLB 容器完成（%s）" % doc.asset_version)
    vrm = VRM.parse_vrm(doc)
    log("识别到 %s：%s" % ("VRM 1.0" if vrm.version == 1 else "VRM 0.x",
                          vrm.meta.get("name") or "(未命名)"))
    for w in vrm.warnings:
        result.warnings.append(w)

    if out_dir is None:
        out_dir = os.path.dirname(os.path.abspath(vrm_path))
    os.makedirs(out_dir, exist_ok=True)

    ground_offset = 0.0
    if options.ground_align:
        min_y = _scan_min_y(doc)
        if min_y is not None:
            ground_offset = -min_y * options.unit_scale
            log("脚底对齐：整体抬高 %.3f 个 MMD 单位" % ground_offset)

    tf = Transform(doc, options.unit_scale, ground_offset)
    log("坐标变换：%s" % tf)

    check()
    bones = MB.build_bones(vrm, tf)
    log("骨骼映射完成：%d 根（VRM 人形骨 %d 个）" % (len(bones.bones),
                                             len(vrm.humanoid_bones)))

    textures = MAT.TexturePool(doc, out_dir)
    check()
    mesh_result = MESH.MeshBuilder(vrm, bones, tf, textures,
                                   options.to_dict()).build()
    log("网格转换完成：%s" % mesh_result)
    for w in mesh_result.warnings:
        result.warnings.append(w)

    morph_list = []
    if options.morphs:
        check()
        morph_list, mw = MORPHS.build_morphs(vrm, mesh_result, bones, tf,
                                             options.to_dict())
        result.warnings.extend(mw)
        log("表情转换完成：%d 个表情" % len(morph_list))

    rigidbodies = []
    joints = []
    if options.physics:
        check()
        rigidbodies, joints, pw = PHYS.PhysicsBuilder(vrm, bones, tf,
                                                      options.to_dict()).build()
        result.warnings.extend(pw)
        log("物理转换完成：%d 刚体 / %d 关节" % (len(rigidbodies), len(joints)))

    check()
    model = P.PmxModel()
    model.version = options.pmx_version
    model.text_encoding = options.text_encoding
    model.additional_uv_count = 0
    model.data_flags = P.DEFAULT_DATA_FLAGS
    model.name = _clip(options.model_name or vrm.meta.get("name")
                       or os.path.splitext(os.path.basename(vrm_path))[0], 50)
    model.english_name = model.name
    model.comment = _build_comment(vrm, options)
    model.english_comment = "Converted from VRM by vrm2pmx"
    model.vertices = mesh_result.vertices
    model.indices = mesh_result.indices
    model.textures = textures.paths
    model.materials = mesh_result.materials
    model.bones = bones.bones
    model.morphs = morph_list
    model.display_slots = _build_display_slots(model)
    model.rigidbodies = rigidbodies
    model.joints = joints

    base = _safe_filename(model.name)
    out_path = os.path.join(out_dir, base + ".pmx")
    check()
    P.write_pmx(out_path, model, text_encoding=options.text_encoding,
                version=options.pmx_version)
    log("写出 PMX：%s" % out_path)

    result.output = out_path
    result.textures = list(textures.written)
    result.stats = {
        "vertices": len(model.vertices),
        "triangles": len(model.indices) // 3,
        "materials": len(model.materials),
        "bones": len(model.bones),
        "morphs": len(model.morphs),
        "rigidbodies": len(model.rigidbodies),
        "joints": len(model.joints),
        "textures": len(model.textures),
        "vrm_version": vrm.version,
        "humanoid_bones": len(vrm.humanoid_bones),
        "expressions": len(vrm.expressions),
        "springs": len(vrm.springs),
        "colliders": len(vrm.colliders),
        "bytes": os.path.getsize(out_path),
    }
    result.elapsed = time.time() - started
    return result


def convert_file(vrm_path, out_dir=None, options=None, progress=None):
    return convert(vrm_path, out_dir, options, progress)


# ------------------------------------------------------------------ 辅助


def _scan_min_y(doc):
    min_y = None
    for mesh in doc.json.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            accessor_index = (prim.get("attributes") or {}).get("POSITION")
            if accessor_index is None:
                continue
            accessor = doc.json["accessors"][accessor_index]
            bound = accessor.get("min")
            if bound and len(bound) >= 3:
                if min_y is None or bound[1] < min_y:
                    min_y = bound[1]
    if min_y is not None:
        return min_y
    # 退路：真的没有 min 就抽样扫一遍
    try:
        for mesh in doc.json.get("meshes") or []:
            for prim in mesh.get("primitives") or []:
                accessor_index = (prim.get("attributes") or {}).get("POSITION")
                if accessor_index is None:
                    continue
                positions, _ = doc.accessor_vec(accessor_index, 3)
                for p in positions:
                    if min_y is None or p[1] < min_y:
                        min_y = p[1]
    except Exception:
        return min_y
    return min_y


def _clip(text, limit):
    text = (text or "").strip() or "model"
    return text[:limit]


def _safe_filename(name):
    out = []
    for ch in name:
        out.append("_" if ch in '\\/:*?"<>|' else ch)
    name = "".join(out).strip().strip(".")
    return name or "model"


def _build_comment(vrm, options):
    meta = vrm.meta
    lines = ["由 VRM 转换而来（vrm2pmx）",
             "源格式：%s" % ("VRM 1.0" if vrm.version == 1 else "VRM 0.x"),
             "单位换算：1 米 = %g 个 MMD 单位" % options.unit_scale,
             ""]
    if meta.get("name"):
        lines.append("模型名：%s" % meta["name"])
    if meta.get("authors"):
        lines.append("作者：%s" % ", ".join(str(a) for a in meta["authors"] if a))
    if meta.get("license"):
        lines.append("授权：%s" % meta["license"])
    if meta.get("avatar_permission"):
        lines.append("允许使用：%s" % meta["avatar_permission"])
    if meta.get("commercial"):
        lines.append("商用：%s" % meta["commercial"])
    lines.append("")
    lines.append("注意：转换后的模型仍受原模型的使用条款约束，")
    lines.append("二次配布或改造前请先确认原作者的要求。")
    return "\n".join(lines)


def _build_display_slots(model):
    """按 MMD 惯例建表示枠：Root/表情/IK/体(上)/腕/指/足/その他。"""
    bone_index = {}
    for i, bone in enumerate(model.bones):
        bone_index.setdefault(bone.name, i)

    def bones(names):
        out = []
        for n in names:
            i = bone_index.get(n)
            if i is not None:
                out.append((0, i))
        return out

    slots = []
    slots.append(P.PmxDisplaySlot("Root", "Root", 1, bones([
        "\u5168\u3066\u306e\u89aa", "\u30bb\u30f3\u30bf\u30fc", "\u30b0\u30eb\u30fc\u30d6",
        "\u8170"])))

    used = set()
    for slot in slots:
        for kind, idx in slot.references:
            used.add((kind, idx))
    slots.append(P.PmxDisplaySlot("\u8868\u60c5", "Exp", 1,
                                  [(1, i) for i in range(len(model.morphs))]))

    ik_names = []
    for side in ("\u5de6", "\u53f3"):
        ik_names.extend([side + "\u8db3IK\u89aa", side + "\u8db3\uff29\uff2b",
                         side + "\u3064\u307e\u5148\uff29\uff2b"])
    slots.append(P.PmxDisplaySlot("\uff29\uff2b", "IK", 0, bones(ik_names)))

    upper = ["\u4e0a\u534a\u8eab", "\u4e0a\u534a\u8eab2", "\u4e0a\u534a\u8eab3",
             "\u9996", "\u982d", "\u4e21\u76ee", "\u5de6\u76ee", "\u53f3\u76ee"]
    for side in ("\u5de6", "\u53f3"):
        upper.append(side + "\u80a9")
    slots.append(P.PmxDisplaySlot("\u4f53(\u4e0a)", "UpperBody", 0, bones(upper)))

    arms = []
    for side in ("\u5de6", "\u53f3"):
        arms.extend([side + "\u8155", side + "\u3072\u3058", side + "\u624b\u9996"])
    slots.append(P.PmxDisplaySlot("\u8155", "Arm", 0, bones(arms)))

    fingers = [b.name for b in model.bones
               if any(k in b.name for k in ("\u89aa\u6307", "\u4eba\u6307",
                                            "\u4e2d\u6307", "\u85ac\u6307",
                                            "\u5c0f\u6307"))]
    slots.append(P.PmxDisplaySlot("\u6307", "Finger", 0, bones(fingers)))

    legs = []
    for side in ("\u5de6", "\u53f3"):
        legs.extend([side + "\u8db3", side + "\u3072\u3056", side + "\u8db3\u9996",
                     side + "\u3064\u307e\u5148"])
    slots.append(P.PmxDisplaySlot("\u8db3", "Leg", 0, bones(legs)))

    for slot in slots:
        for kind, idx in slot.references:
            used.add((kind, idx))

    others = []
    for i in range(len(model.bones)):
        if (0, i) not in used:
            others.append((0, i))
    if others:
        slots.append(P.PmxDisplaySlot("\u305d\u306e\u4ed6", "Etc", 0, others))
    return slots
