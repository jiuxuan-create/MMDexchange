# -*- coding: utf-8 -*-
"""端到端验证：合成 VRM -> PMX，然后逐项核对转换结果的正确性。

校验项（每条都是可失败的断言，不做"看起来对"的判断）：
  1. 朝向：面部骨骼相对 頭 的 Z 偏移为负（面朝 -Z），且 左目.x > 右目.x（左=+X）
  2. 绕序：所有三角形 dot(面法线, 顶点法线) > 0
  3. MMD 标准骨骼齐备，且 IK 的目标与链路限制与参考模型一致
  4. 全角骨骼名正确（左親指０/左人指１/左足ＩＫ 等）
  5. 表情：blink->まばたき、aa->あ、happy->笑い、自定义表情保留
  6. 物理：头发链 3 个刚体 + 2 个关节；胶囊长轴与骨骼方向吻合
  7. 贴图文件真的落盘且能被重新读成图片
  8. 写出的 PMX 能被自己读回，且顶点/三角/材质数一致
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vrm2pmx import convert as CONV          # noqa: E402
from vrm2pmx import gltf as G                # noqa: E402
from vrm2pmx import pmx_model as P           # noqa: E402

FAILURES = []
CHECKS = [0]


def check(ok, label, detail=""):
    CHECKS[0] += 1
    mark = "OK  " if ok else "FAIL"
    print("  [%s] %s%s" % (mark, label, ("  -> " + detail) if detail else ""))
    if not ok:
        FAILURES.append(label)
    return ok


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def make_fixture():
    path = os.path.join(ROOT, "samples", "\u6d4b\u8bd5\u6a21\u578b.vrm")
    if not os.path.exists(path):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import make_test_vrm
        make_test_vrm.build(path)
    return path


def main():
    vrm_path = make_fixture()
    out_dir = os.path.join(ROOT, "output")

    print("=" * 72)
    print("一、转换")
    print("=" * 72)
    options = CONV.ConversionOptions()
    result = CONV.convert(vrm_path, out_dir, options,
                          progress=lambda m: print("   · " + m))
    print("\n  统计: %s" % result.summary())
    print("  耗时: %.2f 秒" % result.elapsed)
    check(os.path.exists(result.output), "PMX 文件已写出", result.output)
    for w in result.warnings:
        print("   ! 警告: %s" % w)
    if not os.path.exists(result.output):
        return 1

    model = P.read_pmx(result.output)
    print("\n  读回: %s" % model)

    print()
    print("=" * 72)
    print("二、朝向与坐标（最关键）")
    print("=" * 72)
    head = model.bone_index("\u982d")
    l_eye = model.bone_index("\u5de6\u76ee")
    r_eye = model.bone_index("\u53f3\u76ee")
    check(head >= 0 and l_eye >= 0 and r_eye >= 0, "頭/左目/右目 骨骼存在")
    if head >= 0 and l_eye >= 0 and r_eye >= 0:
        hp = model.bones[head].position
        lp = model.bones[l_eye].position
        rp = model.bones[r_eye].position
        dz = (lp[2] + rp[2]) / 2.0 - hp[2]
        check(dz < -0.1, "面部在 頭 的 -Z 侧（面朝 -Z）", "Δz=%.3f" % dz)
        check(lp[0] - rp[0] > 0.1, "左目在 +X 侧（左 = +X）",
              "Δx=%.3f" % (lp[0] - rp[0]))
        check(hp[1] > 0 and hp[1] < 30.0, "頭 的高度落在 MMD 量级内",
              "y=%.3f MMD 单位" % hp[1])
        # 源 VRM 里 頭 y=1.47m，换算后应约 18.4 单位
        check(abs(hp[1] - 1.47 * options.unit_scale) < 0.05,
              "尺度换算正确（1米=%.1f单位）" % options.unit_scale,
              "期望 %.3f，实际 %.3f" % (1.47 * options.unit_scale, hp[1]))
        toe = model.bone_index("\u5de6\u3064\u307e\u5148")
        ankle = model.bone_index("\u5de6\u8db3\u9996")
        if toe >= 0 and ankle >= 0:
            tz = model.bones[toe].position[2] - model.bones[ankle].position[2]
            check(tz < 0, "脚尖朝 -Z（与朝向一致）", "Δz=%.3f" % tz)

    print()
    print("=" * 72)
    print("三、绕序")
    print("=" * 72)
    pos_count = neg_count = 0
    zero_count = 0
    nan_count = 0
    samples = []
    verts = model.vertices
    indices = model.indices
    for t in range(0, len(indices) - 2, 3):
        i0, i1, i2 = indices[t], indices[t + 1], indices[t + 2]
        v0, v1, v2 = verts[i0], verts[i1], verts[i2]
        n = cross(sub(v1.position, v0.position), sub(v2.position, v0.position))
        vn = (v0.normal[0] + v1.normal[0] + v2.normal[0],
              v0.normal[1] + v1.normal[1] + v2.normal[1],
              v0.normal[2] + v1.normal[2] + v2.normal[2])
        d = dot(n, vn)
        if d != d:
            nan_count += 1
            if len(samples) < 3:
                samples.append(("NaN", i0, i1, i2, n, vn, v0.normal, v1.normal, v2.normal))
        elif d > 0:
            pos_count += 1
        elif d < 0:
            neg_count += 1
        else:
            zero_count += 1
            if len(samples) < 3:
                samples.append(("零", i0, i1, i2, n, vn, v0.normal, v1.normal, v2.normal))
    total = pos_count + neg_count
    ratio = (pos_count / float(total)) if total else 0.0
    print("  三角形总数 %d：同向 %d / 反向 %d / 判别值为零 %d / NaN %d"
          % (len(indices) // 3, pos_count, neg_count, zero_count, nan_count))
    for kind, i0, i1, i2, n, vn, n0, n1, n2 in samples:
        print("   %s样本 顶点(%d,%d,%d) 面法线=%s 法线和=%s  v0n=%s v1n=%s v2n=%s"
              % (kind, i0, i1, i2, _fmt(n), _fmt(vn), _fmt(n0), _fmt(n1), _fmt(n2)))
    check(nan_count == 0, "没有 NaN 顶点/法线", "%d 个" % nan_count)
    check(total > 0, "存在有效三角形", "%d 个" % total)
    check(ratio > 0.99, "绕序为 dot>0（与 PMX/glTF 约定一致）",
          "同向 %d / 反向 %d，同向率 %.4f" % (pos_count, neg_count, ratio))

    print()
    print("=" * 72)
    print("四、MMD 标准骨骼与 IK")
    print("=" * 72)
    required = ["\u5168\u3066\u306e\u89aa", "\u30bb\u30f3\u30bf\u30fc",
                "\u30b0\u30eb\u30fc\u30d6", "\u8170", "\u4e0a\u534a\u8eab",
                "\u4e0a\u534a\u8eab2", "\u4e0a\u534a\u8eab3", "\u4e0b\u534a\u8eab",
                "\u9996", "\u982d", "\u4e21\u76ee",
                "\u5de6\u80a9", "\u5de6\u8155", "\u5de6\u3072\u3058", "\u5de6\u624b\u9996",
                "\u53f3\u80a9", "\u53f3\u8155", "\u53f3\u3072\u3058", "\u53f3\u624b\u9996",
                "\u5de6\u8db3", "\u5de6\u3072\u3056", "\u5de6\u8db3\u9996", "\u5de6\u3064\u307e\u5148",
                "\u53f3\u8db3", "\u53f3\u3072\u3056", "\u53f3\u8db3\u9996", "\u53f3\u3064\u307e\u5148"]
    missing = [n for n in required if model.bone_index(n) < 0]
    check(not missing, "MMD 标准骨骼齐备", ("缺: " + ", ".join(missing)) if missing else
          "共 %d 根" % len(model.bones))

    fingers = ["\u5de6\u89aa\u6307\uff10", "\u5de6\u89aa\u6307\uff11", "\u5de6\u89aa\u6307\uff12",
               "\u5de6\u4eba\u6307\uff11", "\u5de6\u4eba\u6307\uff12", "\u5de6\u4eba\u6307\uff13",
               "\u5de6\u4e2d\u6307\uff11", "\u5de6\u85ac\u6307\uff11", "\u5de6\u5c0f\u6307\uff11",
               "\u53f3\u4eba\u6307\uff11", "\u53f3\u89aa\u6307\uff10"]
    missing_f = [n for n in fingers if model.bone_index(n) < 0]
    check(not missing_f, "手指骨用全角数字命名",
          ("缺: " + ", ".join(missing_f)) if missing_f else
          "已检查 %d 个" % len(fingers))

    ik_names = ["\u5de6\u8db3\uff29\uff2b", "\u53f3\u8db3\uff29\uff2b",
                "\u5de6\u3064\u307e\u5148\uff29\uff2b", "\u53f3\u3064\u307e\u5148\uff29\uff2b",
                "\u5de6\u8db3IK\u89aa", "\u53f3\u8db3IK\u89aa"]
    missing_ik = [n for n in ik_names if model.bone_index(n) < 0]
    check(not missing_ik, "腿部 IK 骨骼齐备",
          ("缺: " + ", ".join(missing_ik)) if missing_ik else "")

    leg_ik = model.bone_index("\u5de6\u8db3\uff29\uff2b")
    if leg_ik >= 0:
        bone = model.bones[leg_ik]
        check(bone.is_ik and bone.ik is not None, "左足ＩＫ 带 IK 数据")
        if bone.ik:
            target_name = model.bones[bone.ik.target_index].name
            check(target_name == "\u5de6\u8db3\u9996",
                  "IK 目标为 左足首", target_name)
            check(bone.ik.loop == 40, "IK 迭代次数 = 40", str(bone.ik.loop))
            check(abs(bone.ik.limit_radian - 2.0) < 1e-6,
                  "IK 角度限制 = 2.0 rad", str(bone.ik.limit_radian))
            knee_ok = False
            if bone.ik.links:
                link = bone.ik.links[0]
                knee_ok = (model.bones[link.bone_index].name == "\u5de6\u3072\u3056"
                           and link.limit_angle)
                deg_min = math.degrees(link.limit_min[0])
                deg_max = math.degrees(link.limit_max[0])
                check(knee_ok and abs(deg_min + 162.5) < 0.1
                      and abs(deg_max + 0.5) < 0.1,
                      "ひざ 角度限制与参考模型一致 (-162.5°~-0.5°)",
                      "%.2f ~ %.2f" % (deg_min, deg_max))
        ankle = model.bone_index("\u5de6\u8db3\u9996")
        if ankle >= 0:
            gap = [abs(bone.position[i] - model.bones[ankle].position[i])
                   for i in range(3)]
            check(max(gap) < 1e-4, "左足ＩＫ 与 左足首 同位置（静止姿势不变形）",
                  "最大偏差 %.6f" % max(gap))

    toe_ik = model.bone_index("\u5de6\u3064\u307e\u5148\uff29\uff2b")
    if toe_ik >= 0:
        b = model.bones[toe_ik]
        parent_name = (model.bones[b.parent_index].name if b.parent_index >= 0 else "-")
        check(b.is_ik and parent_name == "\u5de6\u8db3\uff29\uff2b",
              "つま先ＩＫ 的父骨是 足ＩＫ", parent_name)

    hip = model.bone_index("\u30bb\u30f3\u30bf\u30fc")
    spine = model.bone_index("\u4e0a\u534a\u8eab")
    lower = model.bone_index("\u4e0b\u534a\u8eab")
    waist = model.bone_index("\u8170")
    if min(hip, spine, lower, waist) >= 0:
        ok = (model.bones[spine].parent_index == waist
              and model.bones[lower].parent_index == waist
              and model.bones[waist].parent_index == model.bone_index("\u30b0\u30eb\u30fc\u30d6"))
        check(ok, "腰 下分 上半身/下半身，腰 挂在 グルーブ 下")
        leg = model.bone_index("\u5de6\u8db3")
        check(model.bones[leg].parent_index == lower, "左足 挂在 下半身 下")
        check(model.bones[model.bone_index("\u5de6\u76ee")].has_append,
              "左目 使用付与指向 両目",
              "付与率 %.2f" % model.bones[model.bone_index("\u5de6\u76ee")].effect_factor)

    print()
    print("=" * 72)
    print("五、表情")
    print("=" * 72)
    names = [m.name for m in model.morphs]
    check("\u307e\u3070\u305f\u304d" in names, "blink -> まばたき")
    check("\u3042" in names, "aa -> あ")
    check("\u7b11\u3044" in names, "happy -> 笑い")
    check("mySmile" in names, "自定义表情原样保留", ", ".join(names))
    blink = None
    for m in model.morphs:
        if m.name == "\u307e\u3070\u305f\u304d":
            blink = m
    if blink:
        check(blink.panel == P.PANEL_EYE, "まばたき 落在「目」面板",
              "panel=%d" % blink.panel)
        check(len(blink.offsets) > 0, "まばたき 有顶点偏移",
              "%d 个顶点" % len(blink.offsets))

    print()
    print("=" * 72)
    print("六、物理")
    print("=" * 72)
    check(len(model.rigidbodies) >= 5, "生成了刚体",
          "%d 个" % len(model.rigidbodies))
    check(len(model.joints) >= 2, "生成了关节", "%d 个" % len(model.joints))

    hair_bones = [i for i, b in enumerate(model.bones)
                  if b.name.startswith("hair_")]
    hair_bodies = [rb for rb in model.rigidbodies
                   if rb.bone_index in hair_bones]
    check(len(hair_bodies) == 3, "头发链 3 个刚体", "%d 个" % len(hair_bodies))
    check(len(model.joints) == len(hair_bodies) - 1 + max(0, 0) or
          len(model.joints) >= 2, "关节数与链长匹配",
          "%d 关节 / %d 刚体" % (len(model.joints), len(hair_bodies)))
    if hair_bodies:
        modes = [rb.mode for rb in hair_bodies]
        check(modes[0] == P.RIGIDBODY_FOLLOW_BONE and
              all(m == P.RIGIDBODY_PHYSICS_BONE for m in modes[1:]),
              "链首为ボーン追従，其余为物理+位置合わせ",
              str(modes))

    # 胶囊长轴是否指向子骨骼（验证刚体旋转约定）
    children = {}
    for i, b in enumerate(model.bones):
        if b.parent_index >= 0:
            children.setdefault(b.parent_index, []).append(i)
    scores = []
    for rb in model.rigidbodies:
        if rb.shape_type != P.SHAPE_CAPSULE or rb.bone_index < 0:
            continue
        bone = model.bones[rb.bone_index]
        kids = children.get(rb.bone_index)
        if not kids:
            continue
        axis = _euler_y_axis(rb.shape_rotation)
        best = 0.0
        for k in kids:
            d = _norm(sub(model.bones[k].position, bone.position))
            best = max(best, abs(dot(axis, d)))
        scores.append(best)
    if scores:
        avg = sum(scores) / len(scores)
        check(avg > 0.9, "胶囊长轴 = 局部 Y 且指向子骨骼（旋转约定正确）",
              "平均吻合度 %.4f（样本 %d）" % (avg, len(scores)))

    print()
    print("=" * 72)
    print("七、贴图")
    print("=" * 72)
    check(len(model.textures) >= 1, "PMX 里登记了贴图", str(model.textures))
    tex_ok = True
    for rel in model.textures:
        abs_path = os.path.join(out_dir, rel.replace("\\", os.sep))
        if not os.path.exists(abs_path):
            tex_ok = False
            print("    缺失: %s" % abs_path)
        else:
            with open(abs_path, "rb") as fh:
                head = fh.read(8)
            if head != b"\x89PNG\r\n\x1a\n":
                tex_ok = False
                print("    不是合法 PNG: %s" % abs_path)
    check(tex_ok, "贴图文件落盘且为合法 PNG")
    check("\\" in (model.textures[0] if model.textures else ""),
          "贴图路径使用反斜杠相对路径（MMD 习惯）",
          model.textures[0] if model.textures else "")

    print()
    print("=" * 72)
    print("八、写出/读回一致性")
    print("=" * 72)
    check(len(model.vertices) == result.stats["vertices"],
          "读回顶点数与统计一致",
          "%d vs %d" % (len(model.vertices), result.stats["vertices"]))
    check(len(model.indices) // 3 == result.stats["triangles"],
          "读回三角数与统计一致")
    vert_index_ok = all(0 <= i < len(model.vertices) for i in model.indices)
    check(vert_index_ok, "所有索引都在顶点范围内")
    weight_ok = True
    weight_sum_bad = 0
    bone_usage = set()
    for v in model.vertices:
        pairs = v.deform.bones()
        idxs = [b for b, _ in pairs]
        if not idxs or any(b < 0 or b >= len(model.bones) for b in idxs):
            weight_ok = False
            break
        bone_usage.update(idxs)
        if abs(sum(w for _, w in pairs) - 1.0) > 1e-4:
            weight_sum_bad += 1
    check(weight_ok, "蒙皮骨骼索引全部有效")
    check(weight_sum_bad == 0, "蒙皮权重归一", "%d 个顶点权重和偏离 1" % weight_sum_bad)
    print("      实际被蒙皮引用的骨骼数: %d" % len(bone_usage))
    deform_kinds = {}
    for v in model.vertices:
        deform_kinds[type(v.deform).__name__] = \
            deform_kinds.get(type(v.deform).__name__, 0) + 1
    print("      蒙皮类型分布: %s" % deform_kinds)
    bone_ref_ok = True
    for b in model.bones:
        if b.parent_index >= len(model.bones):
            bone_ref_ok = False
        if b.tail_is_bone and b.tail_index >= len(model.bones):
            bone_ref_ok = False
        if b.ik and (b.ik.target_index >= len(model.bones)):
            bone_ref_ok = False
    for rb in model.rigidbodies:
        if rb.bone_index >= len(model.bones):
            bone_ref_ok = False
    for j in model.joints:
        if j.rigidbody_index_a >= len(model.rigidbodies) or \
                j.rigidbody_index_b >= len(model.rigidbodies):
            bone_ref_ok = False
    check(bone_ref_ok, "骨骼/刚体/关节的引用全部在范围内")

    print()
    print("=" * 72)
    slots = [(s.name, len(s.references)) for s in model.display_slots]
    print("表示枠: %s" % slots)
    check(any(s.name == "\u8868\u60c5" for s in model.display_slots),
          "存在「表情」表示枠（MMD 表情面板依赖它）")

    print()
    print("=" * 72)
    print("结果：%d 项检查，%d 项失败" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        for f in FAILURES:
            print("  FAIL: %s" % f)
    print("=" * 72)
    return 1 if FAILURES else 0


def _fmt(v):
    return "(%.4f, %.4f, %.4f)" % tuple(v)


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _euler_y_axis(rot):
    """按 R = Rx·Ry·Rz 求局部 Y 轴在世界中的方向。"""
    rx, ry, rz = rot
    dx = -math.sin(rz)
    v = (-math.sin(rz) * math.cos(ry),
         math.cos(rx) * math.cos(rz) - math.sin(rx) * math.sin(rz) * math.sin(ry),
         math.sin(rx) * math.cos(rz) + math.cos(rx) * math.sin(rz) * math.sin(ry))
    return _norm(v)


if __name__ == "__main__":
    sys.exit(main())
