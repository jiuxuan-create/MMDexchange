# -*- coding: utf-8 -*-
"""PMX 结构查看器（开发 / 排障用）。

用法：
    python tools/inspect_pmx.py <模型.pmx> [--full]

输出内容：
    1) 头部：版本、文本编码、追加UV数、各索引宽度
    2) 规模：顶点 / 面 / 纹理 / 材质 / 骨骼 / 表情 / 刚体 / 关节 数量
    3) 朝向与尺度：由 左目/右目 的 X、つま先/足首 的 Z、頭 的 Y 推断
    4) 默认精简列出骨骼名、材质、表情、表示枠；--full 时全部展开
"""

import argparse
import io
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vrm2pmx import pmx_model as P  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def dump_header(path):
    with open(path, "rb") as f:
        head = f.read(48)
    print("=== 头部 ===")
    print("magic           :", head[:4])
    import struct
    print("version         :", struct.unpack_from("<f", head, 4)[0])
    print("格納データ数    :", head[8])
    print("テキストエンコード:", head[9], "(0=UTF-16LE, 1=UTF-8)")
    print("追加UV数        :", head[10])
    print("索引宽度 (顶,纹,材,骨,表,刚):", list(head[11:17]))


def dump_scale(model):
    print("\n=== 规模 ===")
    print("vertices    :", len(model.vertices))
    print("indices     :", len(model.indices), "-> triangles", len(model.indices) // 3)
    print("textures    :", len(model.textures))
    print("materials   :", len(model.materials))
    print("bones       :", len(model.bones))
    print("morphs      :", len(model.morphs))
    print("display     :", len(model.display_slots))
    print("rigidbodies :", len(model.rigidbodies))
    print("joints      :", len(model.joints))
    if model.vertices:
        d = model.vertices[0].deform
        kinds = Counter(v.deform.kind for v in model.vertices)
        print("蒙皮类型分布 :", {k: n for k, n in sorted(kinds.items())})
        print("追加UV层数   :", len(model.vertices[0].additional_uv))
    print("材质索引合计 :", sum(m.index_count for m in model.materials),
          "（应等于 indices）")


def dump_axes(model):
    print("\n=== 朝向 / 尺度 ===")
    idx = {}
    for i, b in enumerate(model.bones):
        idx.setdefault(b.name, i)

    for name in ("センター", "グルーブ", "腰", "上半身", "上半身2", "首", "頭",
                 "左肩", "左腕", "左ひじ", "左手首", "下半身",
                 "左足", "左ひざ", "左足首", "左つま先", "左目", "右目", "両目"):
        i = idx.get(name)
        if i is None:
            continue
        b = model.bones[i]
        print("  %-8s idx=%-4d parent=%-4d pos=(%9.4f,%9.4f,%9.4f)"
              % (name, i, b.parent_index, b.position[0], b.position[1], b.position[2]))

    leye, reye = idx.get("左目"), idx.get("右目")
    if leye is not None and reye is not None:
        dx = model.bones[leye].position[0] - model.bones[reye].position[0]
        print("  左目.x - 右目.x = %+.4f  -> 左 = %s"
              % (dx, "+X" if dx > 0 else "-X"))

    toe, ankle = idx.get("左つま先"), idx.get("左足首")
    if toe is not None and ankle is not None:
        dz = model.bones[toe].position[2] - model.bones[ankle].position[2]
        print("  左つま先.z - 左足首.z = %+.4f  -> 模型朝 %s"
              % (dz, "+Z（正对 +Z）" if dz > 0 else "-Z（正对 -Z）"))

    head = idx.get("頭")
    if head is not None:
        y = model.bones[head].position[1]
        print("  頭.y = %.4f  (若身高 1.55m，则 1 unit ≈ %.2f cm)" % (y, 155.0 / y if y else 0))

    # 顶点包围盒，用于交叉验证尺度
    if model.vertices:
        xs = [v.position[0] for v in model.vertices]
        ys = [v.position[1] for v in model.vertices]
        zs = [v.position[2] for v in model.vertices]
        print("  顶点包围盒 X[%.3f, %.3f] Y[%.3f, %.3f] Z[%.3f, %.3f]"
              % (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))
        print("  身高(顶点最高) = %.3f units" % max(ys))


def dump_bones(model, full):
    print("\n=== 骨骼 (%d) ===" % len(model.bones))
    limit = len(model.bones) if full else 60
    for i, b in enumerate(model.bones[:limit]):
        tags = []
        if b.is_ik:
            tags.append("IK")
        if b.has_append:
            tags.append("付与->%d(%.2f)" % (b.effect_index, b.effect_factor))
        if b.flag & P.BONEFLAG_HAS_FIXED_AXIS:
            tags.append("軸固定")
        if b.flag & P.BONEFLAG_IS_AFTER_PHYSICS_DEFORM:
            tags.append("物理後")
        print(" [%3d] %-18s parent=%-4d pos=(%8.3f,%8.3f,%8.3f) layer=%d flag=0x%04x %s"
              % (i, b.name, b.parent_index, b.position[0], b.position[1],
                 b.position[2], b.layer, b.flag, " ".join(tags)))
    if not full and len(model.bones) > limit:
        print("  ... 其余 %d 根省略" % (len(model.bones) - limit))


def dump_materials(model, full):
    print("\n=== 材质 (%d) ===" % len(model.materials))
    limit = len(model.materials) if full else 30
    for i, m in enumerate(model.materials[:limit]):
        print(" [%2d] %-22s tex=%-3d sph=%-3d/%d toon=%d/%d flag=0x%02x idx=%d "
              "dif=(%.2f,%.2f,%.2f,%.2f) edge=%.2f"
              % (i, m.name, m.texture_index, m.sphere_texture_index,
                 m.sphere_mode, m.toon_texture_index, m.toon_sharing_flag,
                 m.flag, m.index_count, m.diffuse[0], m.diffuse[1],
                 m.diffuse[2], m.diffuse[3], m.edge_size))
    if not full and len(model.materials) > limit:
        print("  ... 其余 %d 个省略" % (len(model.materials) - limit))
    print("  纹理列表 (%d):" % len(model.textures))
    tlimit = len(model.textures) if full else 20
    for i, t in enumerate(model.textures[:tlimit]):
        print("   [%2d] %s" % (i, t))


def dump_morphs(model, full):
    print("\n=== 表情 (%d) ===" % len(model.morphs))
    panels = Counter()
    kinds = Counter()
    for mo in model.morphs:
        panels[mo.panel] += 1
        kinds[mo.morph_type] += 1
    print("  panel 分布:", dict(sorted(panels.items())), " type 分布:", dict(sorted(kinds.items())))
    limit = len(model.morphs) if full else 60
    for i, mo in enumerate(model.morphs[:limit]):
        print(" [%3d] panel=%d type=%d %-16s offsets=%d"
              % (i, mo.panel, mo.morph_type, mo.name, len(mo.offsets)))
    if not full and len(model.morphs) > limit:
        print("  ... 其余 %d 个省略" % (len(model.morphs) - limit))


def dump_physics(model, full):
    shapes = {0: "球", 1: "箱", 2: "胶囊"}
    modes = {0: "追従", 1: "物理", 2: "物理+位置合わせ"}
    print("\n=== 刚体 (%d) ===" % len(model.rigidbodies))
    grp = Counter(rb.collision_group for rb in model.rigidbodies)
    print("  collision_group 分布:", dict(sorted(grp.items())))
    print("  shape 分布:", dict(Counter(shapes.get(rb.shape_type, rb.shape_type)
                                       for rb in model.rigidbodies)))
    print("  mode 分布:", dict(Counter(modes.get(rb.mode, rb.mode)
                                      for rb in model.rigidbodies)))
    limit = len(model.rigidbodies) if full else 12
    for i, rb in enumerate(model.rigidbodies[:limit]):
        print(" [%3d] %-20s bone=%-4d grp=%d nocol=0x%04x %s size=(%.3f,%.3f,%.3f) "
              "pos=(%.3f,%.3f,%.3f) mass=%.3f linD=%.3f angD=%.3f mode=%s"
              % (i, rb.name, rb.bone_index, rb.collision_group,
                 rb.no_collision_group, shapes.get(rb.shape_type, rb.shape_type),
                 rb.shape_size[0], rb.shape_size[1], rb.shape_size[2],
                 rb.shape_position[0], rb.shape_position[1], rb.shape_position[2],
                 rb.mass, rb.linear_damping, rb.angular_damping,
                 modes.get(rb.mode, rb.mode)))
    if not full and len(model.rigidbodies) > limit:
        print("  ... 其余 %d 个省略" % (len(model.rigidbodies) - limit))

    print("\n=== 关节 (%d) ===" % len(model.joints))
    print("  joint_type 分布:", dict(Counter(j.joint_type for j in model.joints)))
    limit = len(model.joints) if full else 10
    for i, j in enumerate(model.joints[:limit]):
        print(" [%3d] %-20s type=%d a=%-4d b=%-4d pos=(%.3f,%.3f,%.3f) "
              "spT=(%.3f,%.3f,%.3f) spR=(%.3f,%.3f,%.3f)"
              % (i, j.name, j.joint_type, j.rigidbody_index_a, j.rigidbody_index_b,
                 j.position[0], j.position[1], j.position[2],
                 j.spring_constant_translation[0], j.spring_constant_translation[1],
                 j.spring_constant_translation[2],
                 j.spring_constant_rotation[0], j.spring_constant_rotation[1],
                 j.spring_constant_rotation[2]))
    if not full and len(model.joints) > limit:
        print("  ... 其余 %d 个省略" % (len(model.joints) - limit))


def dump_display(model):
    print("\n=== 表示枠 (%d) ===" % len(model.display_slots))
    for i, s in enumerate(model.display_slots):
        names = []
        for kind, index in s.references[:6]:
            if kind == 0 and index < len(model.bones):
                names.append(model.bones[index].name)
            elif kind == 1 and index < len(model.morphs):
                names.append(model.morphs[index].name)
        print(" [%d] %-12s special=%d refs=%d %s"
              % (i, s.name, s.special_flag, len(s.references),
                 "[" + ", ".join(names) + (" ..." if len(s.references) > 6 else "") + "]"))


def dump_ik(model):
    """打印所有 IK 骨骼的完整设置（MMD 动作数据依赖腿部 IK，必须照抄其约定）。"""
    import math
    print("\n=== IK 骨骼详情 ===")
    for i, b in enumerate(model.bones):
        if not b.is_ik or b.ik is None:
            continue
        parent = model.bones[b.parent_index].name if 0 <= b.parent_index < len(model.bones) else "-"
        target = (model.bones[b.ik.target_index].name
                  if 0 <= b.ik.target_index < len(model.bones) else "?")
        print(" [%3d] %-14s parent=%-12s pos=(%.3f,%.3f,%.3f)"
              % (i, b.name, parent, b.position[0], b.position[1], b.position[2]))
        print("        flag=0x%04x tail_is_bone=%s tail_index=%s tail_pos=(%.3f,%.3f,%.3f)"
              % (b.flag, b.tail_is_bone, b.tail_index,
                 b.tail_position[0], b.tail_position[1], b.tail_position[2]))
        print("        target=%s loop=%d limit=%.4f rad (%.2f deg)"
              % (target, b.ik.loop, b.ik.limit_radian,
                 math.degrees(b.ik.limit_radian)))
        for k, link in enumerate(b.ik.links):
            lname = (model.bones[link.bone_index].name
                     if 0 <= link.bone_index < len(model.bones) else "?")
            if link.limit_angle:
                print("        link[%d] %-12s 限制 min=(%.2f,%.2f,%.2f)deg max=(%.2f,%.2f,%.2f)deg"
                      % (k, lname, math.degrees(link.limit_min[0]),
                         math.degrees(link.limit_min[1]), math.degrees(link.limit_min[2]),
                         math.degrees(link.limit_max[0]), math.degrees(link.limit_max[1]),
                         math.degrees(link.limit_max[2])))
            else:
                print("        link[%d] %-12s 无角度限制" % (k, lname))
    # 顺带打印 足首/つま先/目 等关键位置，便于推算 IK 骨骼摆放
    print("\n  参考位置：")
    for name in ("左足", "左ひざ", "左足首", "左つま先", "左足ＩＫ", "左つま先ＩＫ",
                 "左足IK親", "右足ＩＫ", "右つま先ＩＫ", "右足IK親", "全ての親"):
        i = model.bone_index(name)
        if i >= 0:
            p = model.bones[i].position
            print("    %-12s idx=%-4d (%.4f, %.4f, %.4f) parent=%d"
                  % (name, i, p[0], p[1], p[2], model.bones[i].parent_index))


def main():
    ap = argparse.ArgumentParser(description="PMX 结构查看器")
    ap.add_argument("pmx")
    ap.add_argument("--full", action="store_true", help="全部展开，不省略")
    args = ap.parse_args()

    print("文件:", args.pmx)
    dump_header(args.pmx)
    model = P.read_pmx(args.pmx)
    print("\n模型名:", model.name, "| english:", model.english_name)
    print("comment:", (model.comment or "").replace("\n", " ")[:150])
    dump_scale(model)
    dump_axes(model)
    dump_bones(model, args.full)
    dump_materials(model, args.full)
    dump_morphs(model, args.full)
    dump_physics(model, args.full)
    dump_display(model)
    dump_ik(model)


if __name__ == "__main__":
    main()
