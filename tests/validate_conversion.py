# -*- coding: utf-8 -*-
"""通用转换校验器：拿"源 VRM + 产出 PMX"做几何正确性硬校验。

    python tests/validate_conversion.py <源.vrm> [产出.pmx]

不传 pmx 时会先跑一次转换再校验。所有检查都是可失败的断言：
  A 结构完整性    B 绕序        C 朝向（脚尖朝 -Z）   D 尺度与落地
  E 贴图落盘      F 写出读回一致 G 物理刚体旋转约定     H 表情偏移有效性
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

from vrm2pmx import convert as CONV      # noqa: E402
from vrm2pmx import pmx_model as P       # noqa: E402

FAIL = []
NCHECK = [0]


def check(ok, label, detail=""):
    NCHECK[0] += 1
    print("  [%s] %s%s" % ("OK  " if ok else "FAIL", label,
                           ("  -> " + str(detail)) if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(v):
    n = math.sqrt(dot(v, v))
    return (0.0, 0.0, 0.0) if n < 1e-12 else (v[0] / n, v[1] / n, v[2] / n)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    vrm_path = sys.argv[1]
    if len(sys.argv) > 2:
        pmx_path = sys.argv[2]
        result = None
    else:
        out_dir = os.path.join(ROOT, "output",
                               os.path.splitext(os.path.basename(vrm_path))[0])
        result = CONV.convert(vrm_path, out_dir)
        pmx_path = result.output

    print("=" * 74)
    print("校验对象")
    print("=" * 74)
    print("  源 VRM : %s" % vrm_path)
    print("  产出   : %s" % pmx_path)
    if result:
        for w in result.warnings:
            print("  转换警告: %s" % w)
    model = P.read_pmx(pmx_path)
    print("  %s" % model)
    print("  文件大小: %s 字节" % "{:,}".format(os.path.getsize(pmx_path)))

    print()
    print("=" * 74)
    print("A 结构完整性")
    print("=" * 74)
    check(len(model.vertices) > 0, "有顶点", len(model.vertices))
    check(len(model.indices) > 0 and len(model.indices) % 3 == 0,
          "索引数是 3 的整数倍", len(model.indices))
    check(len(model.materials) > 0, "有材质", len(model.materials))
    check(len(model.bones) > 0, "有骨骼", len(model.bones))
    check(len(model.morphs) > 0, "有表情", len(model.morphs))
    check(len(model.display_slots) > 0, "有表示枠", len(model.display_slots))
    check(all(0 <= i < len(model.vertices) for i in model.indices),
          "所有三角形索引都在顶点范围内")
    bad_bone_ref = 0
    roots = 0
    for b in model.bones:
        if b.parent_index == -1:
            roots += 1
        elif not (0 <= b.parent_index < len(model.bones)):
            bad_bone_ref += 1
        if b.tail_is_bone and not (0 <= b.tail_index < len(model.bones)):
            bad_bone_ref += 1
        if b.is_ik and b.ik and not (0 <= b.ik.target_index < len(model.bones)):
            bad_bone_ref += 1
        if b.ik:
            for link in b.ik.links:
                if not (0 <= link.bone_index < len(model.bones)):
                    bad_bone_ref += 1
    check(bad_bone_ref == 0, "骨骼父子/末端/IK 引用全部有效（根骨 parent=-1 属正常）",
          "越界 %d 个 / 根骨 %d 个" % (bad_bone_ref, roots))
    check(roots == 1, "恰好一根根骨（全ての親）", roots)
    bad_rb = sum(1 for rb in model.rigidbodies
                 if not (0 <= rb.bone_index < len(model.bones)))
    check(bad_rb == 0, "刚体骨骼引用全部有效", bad_rb)
    bad_joint = 0
    for j in model.joints:
        if not (0 <= j.rigidbody_index_a < len(model.rigidbodies)):
            bad_joint += 1
        if not (0 <= j.rigidbody_index_b < len(model.rigidbodies)):
            bad_joint += 1
    check(bad_joint == 0, "关节刚体引用全部有效", bad_joint)
    bad_slot = 0
    for s in model.display_slots:
        for kind, idx in s.references:
            limit = len(model.morphs) if kind == 1 else len(model.bones)
            if not (0 <= idx < limit):
                bad_slot += 1
    check(bad_slot == 0, "表示枠引用全部有效", bad_slot)

    # 材质索引覆盖：所有材质 index_count 之和 == 索引总数，且必须首尾相接
    total = sum(m.index_count for m in model.materials)
    check(total == len(model.indices), "材质 index_count 之和等于索引总数",
          "%d vs %d" % (total, len(model.indices)))
    check(all(m.index_count > 0 for m in model.materials),
          "没有 index_count=0 的空材质",
          sum(1 for m in model.materials if m.index_count == 0))

    deform = {}
    weight_bad = 0
    for v in model.vertices:
        pairs = v.deform.bones()
        deform[type(v.deform).__name__] = deform.get(type(v.deform).__name__, 0) + 1
        if abs(sum(w for _, w in pairs) - 1.0) > 1e-3:
            weight_bad += 1
    check(weight_bad == 0, "蒙皮权重归一", "%d 个顶点偏离" % weight_bad)
    print("      蒙皮类型分布: %s" % deform)

    print()
    print("=" * 74)
    print("B 绕序")
    print("=" * 74)
    verts = model.vertices
    indices = model.indices
    pos = neg = zero = 0
    for t in range(0, len(indices) - 2, 3):
        v0 = verts[indices[t]]
        v1 = verts[indices[t + 1]]
        v2 = verts[indices[t + 2]]
        n = cross(sub(v1.position, v0.position), sub(v2.position, v0.position))
        vn = (v0.normal[0] + v1.normal[0] + v2.normal[0],
              v0.normal[1] + v1.normal[1] + v2.normal[1],
              v0.normal[2] + v1.normal[2] + v2.normal[2])
        d = dot(n, vn)
        if d > 0:
            pos += 1
        elif d < 0:
            neg += 1
        else:
            zero += 1
    tot = pos + neg
    ratio = pos / float(tot) if tot else 0.0
    print("  三角 %d：同向 %d / 反向 %d / 退化 %d" % (len(indices) // 3, pos, neg, zero))
    check(ratio >= 0.999, "绕序 dot>0 比例 ≥ 99.9%%", "%.5f" % ratio)

    print()
    print("=" * 74)
    print("C 朝向（脚尖朝 -Z）")
    print("=" * 74)
    facing = []
    for side in ("\u5de6", "\u53f3"):
        toe = model.bone_index(side + "\u3064\u307e\u5148")
        foot = model.bone_index(side + "\u8db3\u9996")
        if toe >= 0 and foot >= 0:
            dz = model.bones[toe].position[2] - model.bones[foot].position[2]
            facing.append(dz)
            print("      %sつま先.z - %s足首.z = %+.4f" % (side, side, dz))
    check(bool(facing) and all(d < 0 for d in facing),
          "脚尖在脚踝的 -Z 侧（模型面朝 -Z，MMD 约定）", facing)
    leye = model.bone_index("\u5de6\u76ee")
    reye = model.bone_index("\u53f3\u76ee")
    if leye >= 0 and reye >= 0:
        dx = model.bones[leye].position[0] - model.bones[reye].position[0]
        check(dx > 0, "左目在 +X 侧（左=+X）", "%+.4f" % dx)

    print()
    print("=" * 74)
    print("D 尺度与落地")
    print("=" * 74)
    ys = [v.position[1] for v in model.vertices]
    xs = [v.position[0] for v in model.vertices]
    zs = [v.position[2] for v in model.vertices]
    print("      包围盒 X[%.2f, %.2f] Y[%.2f, %.2f] Z[%.2f, %.2f]"
          % (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))
    check(8.0 < max(ys) < 30.0, "身高落在 MMD 量级（8~30 单位）", "%.2f" % max(ys))
    check(-1.0 <= min(ys) <= 1.0, "脚底贴近 y=0（±1 单位内）", "%.3f" % min(ys))
    head = model.bone_index("\u982d")
    if head >= 0:
        hy = model.bones[head].position[1]
        check(10.0 < hy < 25.0, "頭 骨骼高度合理", "%.3f" % hy)

    print()
    print("=" * 74)
    print("E 贴图")
    print("=" * 74)
    out_dir = os.path.dirname(pmx_path)
    missing = []
    notpng = []
    for rel in model.textures:
        p = os.path.join(out_dir, rel.replace("\\", os.sep))
        if not os.path.exists(p):
            missing.append(rel)
        else:
            with open(p, "rb") as fh:
                if fh.read(8) != b"\x89PNG\r\n\x1a\n":
                    notpng.append(rel)
    check(not missing, "所有登记贴图都已落盘",
          ("缺 %d 个: %s" % (len(missing), missing[:3])) if missing else
          "%d 个" % len(model.textures))
    check(not notpng, "贴图都是合法 PNG", notpng[:3])
    backslash = all("\\" in t for t in model.textures) if model.textures else True
    check(backslash, "贴图路径为反斜杠相对路径")

    print()
    print("=" * 74)
    print("F 写出/读回一致")
    print("=" * 74)
    tmp = os.path.join(out_dir, "_roundtrip_check.pmx")
    P.write_pmx(tmp, model)
    again = P.read_pmx(tmp)
    same = (len(again.vertices) == len(model.vertices)
            and len(again.indices) == len(model.indices)
            and len(again.bones) == len(model.bones)
            and len(again.materials) == len(model.materials)
            and len(again.morphs) == len(model.morphs)
            and len(again.rigidbodies) == len(model.rigidbodies)
            and len(again.joints) == len(model.joints)
            and len(again.display_slots) == len(model.display_slots)
            and again.textures == model.textures)
    check(same, "重复写出再读回，各区块数量完全一致")
    vdiff = 0
    for i in range(len(model.vertices)):
        a = model.vertices[i].position
        b = again.vertices[i].position
        if max(abs(a[j] - b[j]) for j in range(3)) > 1e-5:
            vdiff += 1
    check(vdiff == 0, "顶点坐标逐点一致", vdiff)
    bdiff = 0
    for i in range(len(model.bones)):
        if model.bones[i].name != again.bones[i].name:
            bdiff += 1
    check(bdiff == 0, "骨骼名逐根一致", bdiff)
    os.remove(tmp)

    print()
    print("=" * 74)
    print("G 物理刚体旋转约定")
    print("=" * 74)
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
        axis = euler_y_axis(rb.shape_rotation)
        best = 0.0
        for k in kids:
            d = norm(sub(model.bones[k].position, bone.position))
            best = max(best, abs(dot(axis, d)))
        scores.append(best)
    if scores:
        avg = sum(scores) / len(scores)
        check(avg > 0.8, "胶囊长轴（局部 +Y）平均指向子骨骼",
              "吻合度 %.4f / 样本 %d" % (avg, len(scores)))
    else:
        print("      没有可采样的胶囊刚体，跳过")

    print()
    print("=" * 74)
    print("H 表情偏移有效性")
    print("=" * 74)
    bad_off = 0
    vertex_morph_votes = {}
    for m in model.morphs:
        for off in m.offsets:
            if m.morph_type == P.MORPH_VERTEX:
                if not (0 <= off.index < len(model.vertices)):
                    bad_off += 1
                else:
                    vertex_morph_votes[off.index] = \
                        vertex_morph_votes.get(off.index, 0) + 1
            elif m.morph_type == P.MORPH_MATERIAL:
                if not (0 <= off.index < len(model.materials)):
                    bad_off += 1
            elif m.morph_type == P.MORPH_BONE:
                if not (0 <= off.index < len(model.bones)):
                    bad_off += 1
    check(bad_off == 0, "表情偏移索引全部有效", bad_off)
    over = sum(1 for c in vertex_morph_votes.values() if c > 4)
    print("      被 >4 个顶点表情共同影响的顶点: %d（MMD 只取前 4 个）" % over)

    print()
    print("=" * 74)
    print("结果：%d 项检查，%d 项失败" % (NCHECK[0], len(FAIL)))
    for f in FAIL:
        print("  FAIL: %s" % f)
    print("=" * 74)
    return 1 if FAIL else 0


def euler_y_axis(rot):
    rx, ry, rz = rot
    v = (-math.sin(rz) * math.cos(ry),
         math.cos(rx) * math.cos(rz) - math.sin(rx) * math.sin(rz) * math.sin(ry),
         math.sin(rx) * math.cos(rz) + math.cos(rx) * math.sin(rz) * math.sin(ry))
    return norm(v)


if __name__ == "__main__":
    sys.exit(main())
