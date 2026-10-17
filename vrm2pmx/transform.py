# -*- coding: utf-8 -*-
"""坐标变换：VRM/glTF 空间 -> MMD/PMX 空间。

实测约定（见 tools/probe_facing.py 与 tools/probe_winding.py）：
  MMD 模型面朝 -Z、左为 +X、Y 向上 —— 与 glTF 的「面朝 +Z、左为 +X」相比，
  只差一个 Z 取反。所以变换是 (x, y, z) -> (x, y, -z) * 单位比例。

注意 (x,y,z)->(x,y,-z) 是一次镜像（行列式 -1），会让三角形绕序翻转；
而实测 PMX 与 glTF 的绕序约定同为 dot(面法线, 顶点法线) > 0，
因此写出时必须把每个三角形的索引顺序颠倒回来。
"""

__all__ = ["Transform"]

DEFAULT_UNIT_SCALE = 12.5   # 1 米 = 12.5 个 MMD 单位，即 1 单位 ≈ 8cm


class Transform(object):
    """VRM 空间 -> MMD 空间。"""

    def __init__(self, doc, unit_scale=DEFAULT_UNIT_SCALE, ground_offset=0.0):
        self.doc = doc
        self.unit_scale = float(unit_scale)
        self.ground_offset = float(ground_offset)

    def point(self, p):
        """位置：缩放 + Z 取反 + 落地偏移。"""
        s = self.unit_scale
        return (p[0] * s, p[1] * s + self.ground_offset, -p[2] * s)

    def direction(self, v):
        """方向向量：只做 Z 取反（不缩放、不平移）。"""
        return (v[0], v[1], -v[2])

    def delta(self, v):
        """位移量：缩放 + Z 取反（与位置同样的线性部分，但不加落地偏移）。"""
        s = self.unit_scale
        return (v[0] * s, v[1] * s, -v[2] * s)

    def normal(self, n):
        """法线：与方向同样变换，再由调用方归一化。"""
        return (n[0], n[1], -n[2])

    def length(self, value):
        """长度/半径：只缩放。"""
        return value * self.unit_scale

    def __repr__(self):
        return "<Transform 1m=%g单位 groundOffset=%g>" % (self.unit_scale,
                                                          self.ground_offset)
