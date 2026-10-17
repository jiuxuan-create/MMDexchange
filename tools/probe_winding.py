# -*- coding: utf-8 -*-
"""判定模型的三角形绕序约定。

对每个三角形计算面法线 n = (v1-v0) x (v2-v0)，与顶点法线的均值点乘：
    dot > 0  -> 绕序与顶点法线同向（右手 CCW 约定）
    dot < 0  -> 绕序与顶点法线反向（需要把索引顺序倒过来才对得上）

PMX 输出必须沿用 PMX 的既有约定，否则模型在 MMD 里会里外翻面。

用法：
    python tools/probe_winding.py <模型.pmx|模型.vrm>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def report(label, positions, normals, indices, limit=200000):
    pos_count = 0
    neg_count = 0
    zero = 0
    tri = len(indices) // 3
    step = max(1, tri // (limit // 3))
    checked = 0
    for t in range(0, tri, step):
        i0, i1, i2 = indices[t * 3], indices[t * 3 + 1], indices[t * 3 + 2]
        if i0 >= len(positions) or i1 >= len(positions) or i2 >= len(positions):
            continue
        v0, v1, v2 = positions[i0], positions[i1], positions[i2]
        n = cross(sub(v1, v0), sub(v2, v0))
        vn = (normals[i0][0] + normals[i1][0] + normals[i2][0],
              normals[i0][1] + normals[i1][1] + normals[i2][1],
              normals[i0][2] + normals[i1][2] + normals[i2][2])
        d = dot(n, vn)
        if abs(d) < 1e-12:
            zero += 1
        elif d > 0:
            pos_count += 1
        else:
            neg_count += 1
        checked += 1
    print("\n[%s] 抽查 %d 个三角形" % (label, checked))
    print("   dot > 0 (与顶点法线同向): %d" % pos_count)
    print("   dot < 0 (反向)          : %d" % neg_count)
    print("   退化                    : %d" % zero)
    if pos_count or neg_count:
        majority = "dot > 0 (右手 CCW)" if pos_count >= neg_count else "dot < 0 (反向绕序)"
        print("   主流约定: %s" % majority)
    return pos_count, neg_count


def load_pmx(path):
    from vrm2pmx import pmx_model as P
    m = P.read_pmx(path)
    positions = [v.position for v in m.vertices]
    normals = [v.normal for v in m.vertices]
    return positions, normals, list(m.indices)


def load_vrm(path):
    from vrm2pmx import gltf as G
    doc = G.read_gltf(path)
    positions = []
    normals = []
    indices = []
    for mesh in doc.json.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if prim.get("mode", 4) != 4:
                continue
            attrs = prim.get("attributes", {})
            if "POSITION" not in attrs:
                continue
            base = len(positions)
            p, _ = doc.accessor_vec(attrs["POSITION"], 3)
            positions.extend(p)
            if "NORMAL" in attrs:
                nn, _ = doc.accessor_vec(attrs["NORMAL"], 3)
                normals.extend(nn)
            else:
                normals.extend([(0.0, 1.0, 0.0)] * len(p))
            if "indices" in prim:
                idx = doc.accessor_indices(prim["indices"])
                indices.extend([i + base for i in idx])
            else:
                indices.extend(range(base, base + len(p)))
    return positions, normals, indices


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    if path.lower().endswith(".pmx"):
        positions, normals, indices = load_pmx(path)
        label = os.path.basename(path) + " (PMX)"
    else:
        positions, normals, indices = load_vrm(path)
        label = os.path.basename(path) + " (VRM/glTF)"
    print("文件:", path, " 顶点:", len(positions), " 三角:", len(indices) // 3)
    report(label, positions, normals, indices)
    return 0


if __name__ == "__main__":
    sys.exit(main())
