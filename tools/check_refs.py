# -*- coding: utf-8 -*-
"""列出 PMX 里所有无效引用（父子/末端/IK/刚体/关节/表示枠）。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vrm2pmx import pmx_model as P

model = P.read_pmx(sys.argv[1])
nb, nr, nm = len(model.bones), len(model.rigidbodies), len(model.morphs)
print("骨骼 %d / 刚体 %d / 关节 %d / 表情 %d / 材质 %d"
      % (nb, nr, len(model.joints), nm, len(model.materials)))

print("\n--- 根骨（parent_index == -1，属正常）---")
for i, b in enumerate(model.bones):
    if b.parent_index == -1:
        print("  [%3d] %s" % (i, b.name))

print("\n--- parent_index 越界 ---")
bad = 0
for i, b in enumerate(model.bones):
    if b.parent_index != -1 and not (0 <= b.parent_index < nb):
        print("  [%3d] %s parent=%d" % (i, b.name, b.parent_index))
        bad += 1
print("  共 %d 个" % bad)

print("\n--- tail_is_bone 但 tail_index 越界 ---")
bad = 0
for i, b in enumerate(model.bones):
    if b.tail_is_bone and not (0 <= b.tail_index < nb):
        print("  [%3d] %s tail_index=%d" % (i, b.name, b.tail_index))
        bad += 1
print("  共 %d 个" % bad)

print("\n--- IK target 越界 ---")
bad = 0
for i, b in enumerate(model.bones):
    if b.is_ik:
        if b.ik is None:
            print("  [%3d] %s 标记为 IK 但没有 ik 数据" % (i, b.name))
            bad += 1
            continue
        if not (0 <= b.ik.target_index < nb):
            print("  [%3d] %s target=%d" % (i, b.name, b.ik.target_index))
            bad += 1
        for link in b.ik.links:
            if not (0 <= link.bone_index < nb):
                print("  [%3d] %s link=%d" % (i, b.name, link.bone_index))
                bad += 1
print("  共 %d 个" % bad)

print("\n--- 付与骨 effect_index 越界 ---")
bad = 0
for i, b in enumerate(model.bones):
    if b.has_append and not (0 <= b.effect_index < nb):
        print("  [%3d] %s effect_index=%d" % (i, b.name, b.effect_index))
        bad += 1
print("  共 %d 个" % bad)

print("\n--- 刚体骨骼引用越界 ---")
bad = 0
for i, rb in enumerate(model.rigidbodies):
    if not (0 <= rb.bone_index < nb):
        print("  [%3d] %s bone=%d" % (i, rb.name, rb.bone_index))
        bad += 1
print("  共 %d 个" % bad)

print("\n--- 关节刚体引用越界 ---")
bad = 0
for i, j in enumerate(model.joints):
    if not (0 <= j.rigidbody_index_a < nr):
        print("  [%3d] %s a=%d" % (i, j.name, j.rigidbody_index_a))
        bad += 1
    if not (0 <= j.rigidbody_index_b < nr):
        print("  [%3d] %s b=%d" % (i, j.name, j.rigidbody_index_b))
        bad += 1
print("  共 %d 个" % bad)

print("\n--- 表示枠引用越界 ---")
bad = 0
for s in model.display_slots:
    for kind, idx in s.references:
        limit = nm if kind == 1 else nb
        if not (0 <= idx < limit):
            print("  [%s] kind=%d idx=%d" % (s.name, kind, idx))
            bad += 1
print("  共 %d 个" % bad)

print("\n--- 骨骼名为空的骨骼 ---")
empty = [i for i, b in enumerate(model.bones) if not b.name.strip()]
print("  %d 个 %s" % (len(empty), empty[:10]))

print("\n--- 重名骨骼 ---")
seen = {}
dup = []
for i, b in enumerate(model.bones):
    seen.setdefault(b.name, []).append(i)
for k, v in seen.items():
    if len(v) > 1:
        dup.append((k, v))
print("  %d 组 %s" % (len(dup), dup[:8]))
