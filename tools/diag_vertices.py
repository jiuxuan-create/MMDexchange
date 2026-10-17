# -*- coding: utf-8 -*-
"""诊断：把输出 PMX 的前几个盒子的顶点坐标打出来，定位退化面。"""
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

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "output", "vrm2pmx 测试模型.pmx")
model = P.read_pmx(path)

print("前 32 个顶点：")
for i in range(min(32, len(model.vertices))):
    v = model.vertices[i]
    print("  [%2d] pos=(%9.5f,%9.5f,%9.5f) n=(%6.3f,%6.3f,%6.3f) uv=(%.3f,%.3f) %s"
          % (i, v.position[0], v.position[1], v.position[2],
             v.normal[0], v.normal[1], v.normal[2], v.uv[0], v.uv[1],
             type(v.deform).__name__))

print("\n前 12 个三角形：")
for t in range(0, min(36, len(model.indices)), 3):
    a, b, c = model.indices[t], model.indices[t+1], model.indices[t+2]
    pa, pb, pc = model.vertices[a].position, model.vertices[b].position, \
        model.vertices[c].position
    ux, uy, uz = pb[0]-pa[0], pb[1]-pa[1], pb[2]-pa[2]
    vx, vy, vz = pc[0]-pa[0], pc[1]-pa[1], pc[2]-pa[2]
    nx = uy*vz-uz*vy
    ny = uz*vx-ux*vz
    nz = ux*vy-uy*vx
    print("  (%d,%d,%d) 面法线=(%.5f,%.5f,%.5f)" % (a, b, c, nx, ny, nz))
