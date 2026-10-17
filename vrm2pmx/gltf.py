# -*- coding: utf-8 -*-
"""glTF 2.0 / GLB 容器解析。

VRM 文件本质就是带扩展的 glTF 2.0（.vrm 即 GLB 二进制容器）。本模块只负责
"容器层"的事情：GLB 拆块、buffer/bufferView 读取、accessor 解码、节点世界变换、
图片字节取出。VRM 的语义（humanoid / 表情 / SpringBone / MToon）由 vrm.py 处理。

设计取舍：
  * 纯标准库，不引入 pygltflib / numpy 依赖
  * accessor 解码优先走 array.frombytes（连续、无 byteStride 时），大模型也不慢
  * 带缓存：同一 accessor 只解码一次
"""

import array
import base64
import io
import json
import os
import struct

__all__ = ["GltfDocument", "GltfError", "read_gltf", "read_glb"]

GLB_MAGIC = 0x46546C67
GLB_CHUNK_JSON = 0x4E4F534A
GLB_CHUNK_BIN = 0x004E4942

# componentType -> (struct 字符, 字节数, 是否整型)
COMPONENT_TYPES = {
    5120: ("b", 1, True),    # BYTE
    5121: ("B", 1, True),    # UNSIGNED_BYTE
    5122: ("h", 2, True),    # SHORT
    5123: ("H", 2, True),    # UNSIGNED_SHORT
    5125: ("I", 4, True),    # UNSIGNED_INT
    5126: ("f", 4, False),   # FLOAT
}

TYPE_COMPONENTS = {
    "SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
    "MAT2": 4, "MAT3": 9, "MAT4": 16,
}

# 归一化整型 -> 除数
NORMALIZE_DIVISOR = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}

MIME_EXTENSION = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/ktx2": ".ktx2",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
}


class GltfError(Exception):
    pass


# ------------------------------------------------------------------ 4x4 矩阵
# glTF 矩阵按列主序存放，共 16 个数


IDENTITY = (1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0)


def mat4_mul(a, b):
    """返回 a * b（列主序）。"""
    r = [0.0] * 16
    for col in range(4):
        for row in range(4):
            s = 0.0
            for k in range(4):
                s += a[k * 4 + row] * b[col * 4 + k]
            r[col * 4 + row] = s
    return tuple(r)


def mat4_from_trs(t, q, s):
    """由位移/四元数(xyzw)/缩放构造列主序 4x4。"""
    x, y, z, w = q
    x2, y2, z2 = x + x, y + y, z + z
    xx, xy, xz = x * x2, x * y2, x * z2
    yy, yz, zz = y * y2, y * z2, z * z2
    wx, wy, wz = w * x2, w * y2, w * z2
    sx, sy, sz = s
    return (
        (1.0 - (yy + zz)) * sx, (xy + wz) * sx, (xz - wy) * sx, 0.0,
        (xy - wz) * sy, (1.0 - (xx + zz)) * sy, (yz + wx) * sy, 0.0,
        (xz + wy) * sz, (yz - wx) * sz, (1.0 - (xx + yy)) * sz, 0.0,
        t[0], t[1], t[2], 1.0,
    )


def mat4_transform_point(m, p):
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


def _quat_normalize(q):
    n = (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]) ** 0.5
    if n <= 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def _mat4_normalize_rotation(m):
    """把带缩放的矩阵的旋转列单位化，返回纯旋转矩阵（去掉缩放）。"""
    out = []
    for col in range(3):
        v = (m[col * 4], m[col * 4 + 1], m[col * 4 + 2])
        n = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5
        if n <= 1e-12:
            v = (1.0, 0.0, 0.0) if col == 0 else ((0.0, 1.0, 0.0) if col == 1
                                                  else (0.0, 0.0, 1.0))
        else:
            v = (v[0] / n, v[1] / n, v[2] / n)
        out.extend(v)
    out.extend((0.0, 0.0, 0.0, 1.0))
    return tuple(out)


def _decode_data_uri(uri):
    if not uri.startswith("data:"):
        return None
    comma = uri.find(",")
    if comma < 0:
        raise GltfError("data URI 格式错误")
    header = uri[:comma]
    payload = uri[comma + 1:]
    if ";base64" in header:
        return base64.b64decode(payload)
    return payload.encode("utf-8")


# ------------------------------------------------------------------ 文档


class GltfDocument(object):
    """解析完成的 glTF / GLB 文档。"""

    def __init__(self, gltf, buffers, path=None):
        self.json = gltf
        self.buffers = buffers
        self.path = path
        self.base_dir = os.path.dirname(os.path.abspath(path)) if path else ""
        self._accessor_cache = {}
        self._world_cache = {}
        self._nodes = gltf.get("nodes", [])
        self._parents = self._build_parents()

    # -------------------------------------------------- 基础访问

    @property
    def nodes(self):
        return self._nodes

    @property
    def scenes(self):
        return self.json.get("scenes", [])

    @property
    def asset_version(self):
        return self.json.get("asset", {}).get("version", "")

    @property
    def extensions_used(self):
        return self.json.get("extensionsUsed", [])

    def parent_of(self, node_index):
        return self._parents.get(node_index)

    def _build_parents(self):
        parents = {}
        for i, node in enumerate(self._nodes):
            for child in node.get("children", []) or []:
                parents[child] = i
        return parents

    def scene_roots(self):
        if not self.scenes:
            return [i for i in range(len(self._nodes)) if i not in self._parents]
        scenes = self.json.get("scenes", [])
        idx = self.json.get("scene", 0)
        if idx >= len(scenes):
            idx = 0
        if scenes:
            return list(scenes[idx].get("nodes", []))
        return []

    def ancestors_of(self, node_index):
        chain = []
        cur = self._parents.get(node_index)
        while cur is not None:
            chain.append(cur)
            cur = self._parents.get(cur)
        return chain

    def node_name(self, index):
        name = self._nodes[index].get("name")
        if name:
            return name
        return "node%d" % index

    # -------------------------------------------------- buffer / bufferView

    def buffer_view_bytes(self, index):
        view = self.json["bufferViews"][index]
        buf = self.buffers[view.get("buffer", 0)]
        start = view.get("byteOffset", 0)
        length = view["byteLength"]
        return buf[start:start + length]

    def image_bytes(self, index):
        """返回 (字节, 建议扩展名)。"""
        image = self.json.get("images", [])[index]
        if "bufferView" in image:
            data = self.buffer_view_bytes(image["bufferView"])
            mime = image.get("mimeType", "")
            return data, MIME_EXTENSION.get(mime, ".png")
        uri = image.get("uri")
        if uri is None:
            raise GltfError("image[%d] 既没有 uri 也没有 bufferView" % index)
        inline = _decode_data_uri(uri)
        if inline is not None:
            mime = uri[5:uri.find(",")].split(";")[0]
            return inline, MIME_EXTENSION.get(mime, ".png")
        ext = os.path.splitext(uri)[1] or ".png"
        with io.open(os.path.join(self.base_dir, uri), "rb") as f:
            return f.read(), ext

    # -------------------------------------------------- accessor

    def _read_raw(self, accessor):
        comp_fmt, comp_size, _ = COMPONENT_TYPES[accessor["componentType"]]
        comps = TYPE_COMPONENTS[accessor["type"]]
        count = accessor["count"]
        data = self._read_dense(accessor, comp_fmt, comp_size, comps, count)
        sparse = accessor.get("sparse")
        if sparse:
            self._apply_sparse(accessor, data, comp_fmt, comp_size, comps)
        return data, comps, comp_fmt

    def _read_dense(self, accessor, comp_fmt, comp_size, comps, count):
        total = count * comps
        if "bufferView" not in accessor:
            # 允许 accessor 不引用 bufferView（全 0），规范里合法
            return array.array(comp_fmt, [0] * total)
        view = self.json["bufferViews"][accessor["bufferView"]]
        buf = self.buffers[view.get("buffer", 0)]
        base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        stride = view.get("byteStride")
        element_size = comp_size * comps

        if stride in (None, element_size):
            arr = array.array(comp_fmt)
            raw = buf[base:base + total * comp_size]
            if len(raw) == total * comp_size:
                try:
                    arr.frombytes(raw)
                    if len(arr) == total:
                        return arr
                except ValueError:
                    pass
            # 兜底：逐元素解（例如数据被截断或平台字节序异常）
            unpack = struct.Struct("<" + comp_fmt).unpack_from
            arr = array.array(comp_fmt, [0] * total)
            for i in range(total):
                off = base + i * comp_size
                if off + comp_size <= len(buf):
                    arr[i] = unpack(buf, off)[0]
            return arr

        # 交错存放：逐元素解
        out = array.array(comp_fmt, [0] * total)
        unpack = struct.Struct("<" + comp_fmt).unpack_from
        for i in range(count):
            off = base + i * stride
            for k in range(comps):
                out[i * comps + k] = unpack(buf, off + k * comp_size)[0]
        return out

    def _apply_sparse(self, accessor, data, comp_fmt, comp_size, comps):
        sparse = accessor["sparse"]
        count = sparse["count"]
        # indices
        iview = self.json["bufferViews"][sparse["indices"]["bufferView"]]
        ibuf = self.buffers[iview.get("buffer", 0)]
        ibase = iview.get("byteOffset", 0) + sparse["indices"].get("byteOffset", 0)
        ifmt, isize, _ = COMPONENT_TYPES[sparse["indices"]["componentType"]]
        indices = struct.unpack_from("<%d%s" % (count, ifmt), ibuf, ibase)
        # values
        vview = self.json["bufferViews"][sparse["values"]["bufferView"]]
        vbuf = self.buffers[vview.get("buffer", 0)]
        vbase = vview.get("byteOffset", 0) + sparse["values"].get("byteOffset", 0)
        stride = comp_size * comps
        for n, vi in enumerate(indices):
            off = vbase + n * stride
            for k in range(comps):
                data[vi * comps + k] = struct.unpack_from(
                    "<" + comp_fmt, vbuf, off + k * comp_size)[0]

    def accessor_raw(self, index):
        """返回 (array, components, struct_fmt)；带缓存。"""
        cached = self._accessor_cache.get(index)
        if cached is not None:
            return cached
        accessor = self.json["accessors"][index]
        result = self._read_raw(accessor)
        self._accessor_cache[index] = result
        return result

    def accessor_scaled(self, index):
        """返回 (array, components)；整型带 normalized 时按归一化数值返回。"""
        cache = self._accessor_cache.get(("s", index))
        if cache is not None:
            return cache
        accessor = self.json["accessors"][index]
        data, comps, fmt = self.accessor_raw(index)
        ct = accessor["componentType"]
        if accessor.get("normalized") and ct in NORMALIZE_DIVISOR:
            div = NORMALIZE_DIVISOR[ct]
            out = array.array("f", [0.0] * len(data))
            for i, v in enumerate(data):
                if ct == 5120 or ct == 5122:
                    out[i] = max(-1.0, v / div)
                else:
                    out[i] = v / div
            result = (out, comps)
        else:
            result = (data, comps)
        self._accessor_cache[("s", index)] = result
        return result

    def accessor_floats(self, index):
        """统一转成 float 数组，返回 (array('f'), components)。"""
        cache = self._accessor_cache.get(("f", index))
        if cache is not None:
            return cache
        data, comps = self.accessor_scaled(index)
        if data.typecode == "f":
            result = (data, comps)
        else:
            result = (array.array("f", [float(v) for v in data]), comps)
        self._accessor_cache[("f", index)] = result
        return result

    def accessor_vec(self, index, expect=None):
        """返回 (list[(v0,...,vN)], components)。"""
        data, comps = self.accessor_floats(index)
        if expect is not None and comps != expect:
            raise GltfError("accessor %d 分量数为 %d，期望 %d" % (index, comps, expect))
        count = len(data) // comps
        if comps == 1:
            return list(data), 1
        if comps == 2:
            return [(data[i * 2], data[i * 2 + 1]) for i in range(count)], 2
        if comps == 3:
            return [(data[i * 3], data[i * 3 + 1], data[i * 3 + 2])
                    for i in range(count)], 3
        if comps == 4:
            return [(data[i * 4], data[i * 4 + 1], data[i * 4 + 2], data[i * 4 + 3])
                    for i in range(count)], 4
        return [tuple(data[i * comps:(i + 1) * comps]) for i in range(count)], comps

    def accessor_indices(self, index):
        """索引 accessor -> list[int]。"""
        cache = self._accessor_cache.get(("i", index))
        if cache is not None:
            return cache
        accessor = self.json["accessors"][index]
        data, comps, fmt = self.accessor_raw(index)
        if comps != 1:
            raise GltfError("accessor %d 不是 SCALAR，无法作为索引" % index)
        result = [int(v) for v in data]
        self._accessor_cache[("i", index)] = result
        return result

    # -------------------------------------------------- 节点世界变换

    def local_matrix(self, index):
        node = self._nodes[index]
        if "matrix" in node:
            m = node["matrix"]
            # glTF 的 matrix 已经是列主序
            return tuple(float(v) for v in m)
        t = node.get("translation", (0.0, 0.0, 0.0))
        q = _quat_normalize(node.get("rotation", (0.0, 0.0, 0.0, 1.0)))
        s = node.get("scale", (1.0, 1.0, 1.0))
        return mat4_from_trs(t, q, s)

    def world_matrix(self, index):
        cached = self._world_cache.get(index)
        if cached is not None:
            return cached
        local = self.local_matrix(index)
        parent = self._parents.get(index)
        if parent is None:
            result = local
        else:
            result = mat4_mul(self.world_matrix(parent), local)
        self._world_cache[index] = result
        return result

    def world_translation(self, index):
        """节点原点的世界坐标。"""
        m = self.world_matrix(index)
        return (m[12], m[13], m[14])

    def world_rotation(self, index):
        """节点去掉缩放后的世界旋转（列主序 4x4）。"""
        return _mat4_normalize_rotation(self.world_matrix(index))

    def all_nodes(self):
        return list(range(len(self._nodes)))

    def __repr__(self):
        return "<GltfDocument glTF %s %d节点 %d网格 %d材质 %d蒙皮>" % (
            self.asset_version, len(self._nodes),
            len(self.json.get("meshes", [])), len(self.json.get("materials", [])),
            len(self.json.get("skins", [])))


# ------------------------------------------------------------------ 读入


def read_glb(data, path=None):
    if len(data) < 12:
        raise GltfError("GLB 文件过短")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise GltfError("不是 GLB 文件（magic 0x%08X）" % magic)
    if version != 2:
        raise GltfError("不支持的 GLB 版本 %d" % version)
    if length > len(data):
        raise GltfError("GLB 声明长度 %d 超过实际 %d 字节（文件可能不完整）"
                        % (length, len(data)))

    offset = 12
    gltf = None
    bin_chunk = None
    while offset + 8 <= length:
        clen, ctype = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset:offset + clen]
        offset += clen
        if ctype == GLB_CHUNK_JSON:
            gltf = json.loads(chunk.decode("utf-8"))
        elif ctype == GLB_CHUNK_BIN:
            bin_chunk = chunk
    if gltf is None:
        raise GltfError("GLB 中找不到 JSON 块")

    buffers = []
    for i, buf in enumerate(gltf.get("buffers", [])):
        uri = buf.get("uri")
        if uri is None:
            if bin_chunk is None:
                raise GltfError("buffer[%d] 需要 BIN 块，但 GLB 里没有" % i)
            buffers.append(bin_chunk)
        else:
            inline = _decode_data_uri(uri)
            if inline is not None:
                buffers.append(inline)
            else:
                with io.open(os.path.join(os.path.dirname(os.path.abspath(path))
                                          if path else "", uri), "rb") as f:
                    buffers.append(f.read())
    return GltfDocument(gltf, buffers, path)


def read_gltf(path):
    """读取 .vrm / .glb / .gltf。"""
    with io.open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"glTF":
        return read_glb(data, path)
    # 纯 JSON 的 .gltf
    try:
        gltf = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise GltfError("既不是 GLB 也不是合法的 glTF JSON: %s" % exc)
    base = os.path.dirname(os.path.abspath(path))
    buffers = []
    for i, buf in enumerate(gltf.get("buffers", [])):
        uri = buf.get("uri")
        if uri is None:
            buffers.append(b"")
        else:
            inline = _decode_data_uri(uri)
            if inline is not None:
                buffers.append(inline)
            else:
                with io.open(os.path.join(base, uri), "rb") as f:
                    buffers.append(f.read())
    return GltfDocument(gltf, buffers, path)
