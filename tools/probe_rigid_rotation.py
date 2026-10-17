# -*- coding: utf-8 -*-
"""反推 PMX 刚体的旋转约定（欧拉角顺序 + 胶囊局部轴）。

做法：真实 PMX 模型里，挂在骨骼上、且处于物理演算模式的胶囊刚体，
其长轴通常沿着该骨骼指向子骨骼的方向。于是遍历所有候选的
「欧拉角顺序 x 局部轴」，看哪个组合能让 Y/ Z 轴与骨骼方向最吻合。

用法：
    python tools/probe_rigid_rotation.py <模型.pmx>
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vrm2pmx import pmx_model as P  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return (1, 0, 0, 0, c, -s, 0, s, c)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return (c, 0, s, 0, 1, 0, -s, 0, c)


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return (c, -s, 0, s, c, 0, 0, 0, 1)


def mmul(a, b):
    r = [0.0] * 9
    for i in range(3):
        for j in range(3):
            r[i * 3 + j] = sum(a[i * 3 + k] * b[k * 3 + j] for k in range(3))
    return tuple(r)


def mvec(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
            m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
            m[6] * v[0] + m[7] * v[1] + m[8] * v[2])


def norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


ORDERS = ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"]
AXES = {"Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}


def main():
    path = sys.argv[1]
    m = P.read_pmx(path)

    children = {}
    for i, b in enumerate(m.bones):
        children.setdefault(b.parent_index, []).append(i)

    samples = []
    for idx, rb in enumerate(m.rigidbodies):
        if rb.shape_type != P.SHAPE_CAPSULE or rb.bone_index < 0:
            continue
        if rb.mode == P.RIGIDBODY_FOLLOW_BONE:
            continue
        bone = m.bones[rb.bone_index]
        dirs = []
        for ci in children.get(rb.bone_index, []):
            cb = m.bones[ci]
            d = norm((cb.position[0] - bone.position[0],
                      cb.position[1] - bone.position[1],
                      cb.position[2] - bone.position[2]))
            if d != (0.0, 0.0, 0.0):
                dirs.append(d)
        # 也把"从父骨骼指向本骨骼"作为候选方向（部分刚体是朝父方向对齐的）
        pi = bone.parent_index
        if pi >= 0:
            pb = m.bones[pi]
            d = norm((bone.position[0] - pb.position[0],
                      bone.position[1] - pb.position[1],
                      bone.position[2] - pb.position[2]))
            if d != (0.0, 0.0, 0.0):
                dirs.append(d)
        if dirs:
            samples.append((idx, rb, dirs))

    print("可用的胶囊刚体样本数:", len(samples))
    print("刚体旋转范围为弧度；下面比较各约定下局部轴与世界骨骼方向的平均吻合度\n")

    # 只用"明显非竖直"的样本，才能把欧拉角顺序区分开
    def slanted(dirs):
        return min(abs(d[1]) for d in dirs) < 0.94

    KEY_SAMPLES = [s for s in samples if slanted(s[2])]
    print("其中明显非竖直（与竖直方向夹角 > 20°）的样本数:", len(KEY_SAMPLES))

    def score_over(subset, order, axis):
        total = 0.0
        for idx, rb, dirs in subset:
            rx, ry, rz = rb.shape_rotation
            mats = {"X": rot_x(rx), "Y": rot_y(ry), "Z": rot_z(rz)}
            r = (1, 0, 0, 0, 1, 0, 0, 0, 1)
            for ch in reversed(order):
                r = mmul(r, mats[ch])
            v = norm(mvec(r, axis))
            total += max(abs(dot(v, d)) for d in dirs)
        return total / len(subset) if subset else 0.0

    for label, subset in (("全部样本", samples), ("仅非竖直样本", KEY_SAMPLES)):
        print("--- %s (%d) ---" % (label, len(subset)))
        ranked = sorted(
            ((score_over(subset, order, axis), order, axis_name)
             for order in ORDERS for axis_name, axis in AXES.items()),
            key=lambda t: -t[0])
        for sc, order, axis in ranked[:8]:
            print("  顺序=%-4s 局部轴=%s 平均吻合度=%.4f" % (order, axis, sc))
        print("  最佳: 顺序=%s 轴=%s (%.4f)\n" % (ranked[0][1], ranked[0][2], ranked[0][0]))

    ranked = sorted(
        ((score_over(KEY_SAMPLES or samples, order, axis), order, axis_name)
         for order in ORDERS for axis_name, axis in AXES.items()),
        key=lambda t: -t[0])
    (best_score, best_order, best_axis) = ranked[0]
    print("最可能的约定：欧拉顺序 %s，胶囊长轴 = 局部 %s 轴（平均吻合度 %.4f）"
          % (best_order, best_axis, best_score))


    # 也检查"箱"型刚体对局部轴的取向，作为旁证
    print("\n旁证：位置与骨骼中点/长度的对应关系（前 10 个胶囊）")
    for idx, rb, dirs in samples[:10]:
        bone = m.bones[rb.bone_index]
        ci = children[rb.bone_index][0]
        cb = m.bones[ci]
        mid = ((bone.position[0] + cb.position[0]) / 2,
               (bone.position[1] + cb.position[1]) / 2,
               (bone.position[2] + cb.position[2]) / 2)
        seg = math.sqrt(sum((cb.position[k] - bone.position[k]) ** 2 for k in range(3)))
        bp = rb.shape_position
        print("  [%3d] %-16s 骨骼长=%.3f 刚体size=(%.3f,%.3f,%.3f) "
              "刚体pos与骨骼起点距离=%.3f 与中点距离=%.3f"
              % (idx, rb.name, seg, rb.shape_size[0], rb.shape_size[1],
                 rb.shape_size[2],
                 math.sqrt(sum((bp[k] - bone.position[k]) ** 2 for k in range(3))),
                 math.sqrt(sum((bp[k] - mid[k]) ** 2 for k in range(3)))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
