# -*- coding: utf-8 -*-
"""网格转换：glTF 顶点/索引/蒙皮 -> PMX 顶点与索引。

要点：
  * 每个三角形都要颠倒索引顺序（坐标变换是镜像，见 transform.py）
  * 面按材质分组输出，保证 PMX 材质的 index_count 覆盖连续区间
  * 蒙皮权重直接映射到 BDEF1/2/4（glTF 上限即 4 根骨，天然满足）
  * 静止姿势下 joint * inverseBindMatrix 通常接近单位矩阵，此时跳过变换以提速
"""

import math

from . import gltf as G
from . import pmx_model as P
from . import materials as MAT

__all__ = ["MeshBuilder", "MeshResult"]

MAX_WEIGHTS = 4


class MeshResult(object):
    def __init__(self):
        self.vertices = []
        self.indices = []
        self.materials = []
        self.spans = []
        self.gltf_material_to_pmx = {}
        self.triangle_count = 0
        self.warnings = []

    def __repr__(self):
        return "<MeshResult %d顶点 %d三角 %d材质>" % (
            len(self.vertices), self.triangle_count, len(self.materials))


def _normalize(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n <= 1e-12:
        return (0.0, 1.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _mat3_of(m):
    return (m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10])


def _mat3_apply(a3, v):
    return (a3[0] * v[0] + a3[1] * v[1] + a3[2] * v[2],
            a3[3] * v[0] + a3[4] * v[1] + a3[5] * v[2],
            a3[6] * v[0] + a3[7] * v[1] + a3[8] * v[2])


def _mat4_is_identity(m, eps=1e-5):
    for col in range(3):
        for row in range(3):
            want = 1.0 if col == row else 0.0
            if abs(m[col * 4 + row] - want) > eps:
                return False
    return abs(m[12]) < eps and abs(m[13]) < eps and abs(m[14]) < eps


class MeshBuilder(object):
    def __init__(self, vrm, bones, transform, textures, options=None):
        self.vrm = vrm
        self.doc = transform.doc
        self.bones = bones
        self.transform = transform
        self.textures = textures
        self.options = options or {}
        self.flip_v = bool(self.options.get("flip_v", False))

    # -------------------------------------------------- 入口
    def build(self):
        result = MeshResult()
        items = self._collect_draw_items()
        if not items:
            raise G.GltfError("文件里没有任何三角网格，无法转换")

        items.sort(key=lambda it: (it["material"], it["node"], it["prim"]))
        used = set(it["material"] for it in items)
        result.materials, result.gltf_material_to_pmx = MAT.build_materials(
            self.vrm, self.textures, options=self.options, used=used)

        counts = [0] * len(result.materials)
        for it in items:
            mat_index = result.gltf_material_to_pmx.get(it["material"])
            if mat_index is None:
                mat_index = result.gltf_material_to_pmx.get(-1)
            span = self._emit_primitive(it, result, mat_index)
            counts[mat_index] += span["triangles"]
            result.spans.append(span)

        for mat, n in zip(result.materials, counts):
            mat.index_count = n * 3
        for w in getattr(self.textures, "warnings", []):
            result.warnings.append(w)
        return result

    # -------------------------------------------------- 收集
    def _collect_draw_items(self):
        doc = self.doc
        items = []
        for node_index in range(len(doc.nodes)):
            node = doc.nodes[node_index]
            if "mesh" not in node:
                continue
            mesh_index = node["mesh"]
            if mesh_index >= len(doc.json.get("meshes") or []):
                continue
            mesh = doc.json["meshes"][mesh_index]
            skin = node.get("skin", -1 if "skin" not in node else node["skin"])
            if "skin" not in node:
                skin = -1
            for prim_index, prim in enumerate(mesh.get("primitives") or []):
                if prim.get("mode", 4) != 4:
                    continue
                attrs = prim.get("attributes") or {}
                if "POSITION" not in attrs:
                    continue
                items.append({
                    "node": node_index,
                    "mesh": mesh_index,
                    "prim": prim_index,
                    "material": prim.get("material", -1),
                    "skin": skin,
                    "targets": list(prim.get("targets") or []),
                })
        return items

    # -------------------------------------------------- 单个 primitive
    def _emit_primitive(self, item, result, mat_index):
        doc = self.doc
        prim = doc.json["meshes"][item["mesh"]]["primitives"][item["prim"]]
        attrs = prim["attributes"]
        tf = self.transform

        positions, pc = doc.accessor_vec(attrs["POSITION"], 3)
        count = len(positions)
        if not count:
            return {"triangles": 0, "v_start": len(result.vertices), "v_count": 0,
                    "targets": item["targets"], "mat3": None, "node": item["node"],
                    "mesh": item["mesh"], "prim": item["prim"], "skin_identity": True}

        normals = None
        if "NORMAL" in attrs:
            normals, nc = doc.accessor_vec(attrs["NORMAL"], 3)
            if len(normals) != count:
                normals = None

        raw_indices = None
        if "indices" in prim:
            raw_indices = doc.accessor_indices(prim["indices"])
        if normals is None:
            normals = self._compute_normals(positions, raw_indices, count)

        if "TEXCOORD_0" in attrs:
            uvs, uc = doc.accessor_vec(attrs["TEXCOORD_0"])
            if uc < 2 or len(uvs) != count:
                uvs = [(0.0, 0.0)] * count
        else:
            uvs = [(0.0, 0.0)] * count

        # ---- 蒙皮准备 ----
        skin_joints = None
        skin_mats = None
        bone_mats = None
        skin_identity = True
        if item["skin"] >= 0:
            skin = doc.json["skins"][item["skin"]]
            skin_joints, skin_mats = self._skin_matrices(skin)
            skin_identity = all(_mat4_is_identity(m) for m in skin_mats)
            bone_mats = self._bone_matrix_map(skin_joints, skin_mats)

        joints_raw = weights_raw = jcomps = wcomps = None
        if item["skin"] >= 0 and "JOINTS_0" in attrs and "WEIGHTS_0" in attrs:
            joints_raw, jcomps, _fmt = doc.accessor_raw(attrs["JOINTS_0"])
            if not isinstance(jcomps, int):
                jcomps = 4
            weights_raw, wcomps = doc.accessor_scaled(attrs["WEIGHTS_0"])
            if not isinstance(wcomps, int):
                wcomps = 4

        default_bone = self.bones.bone_for_node(item["node"])
        uv_xform = self._uv_transform(item["material"])
        node_matrix = None
        if item["skin"] < 0:
            node_matrix = doc.world_matrix(item["node"])

        verts_mat3 = [] if not skin_identity else None
        v_start = len(result.vertices)

        for i in range(count):
            weight_list = None
            if joints_raw is not None:
                jc = min(jcomps, MAX_WEIGHTS)
                wc = min(wcomps, MAX_WEIGHTS)
                jbase = i * jcomps
                wbase = i * wcomps
                jl = [int(joints_raw[jbase + k]) for k in range(jc)]
                wl = [float(weights_raw[wbase + k]) for k in range(wc)]
                weight_list = self._combine(jl, wl, skin_joints, default_bone)
            else:
                weight_list = [(default_bone, 1.0)]

            p = positions[i]
            n = normals[i]
            if skin_identity:
                if node_matrix is not None:
                    pw = G.mat4_transform_point(node_matrix, p)
                    nw = _mat3_apply(_mat3_of(node_matrix), n)
                else:
                    pw = p
                    nw = n
                mat3 = None
            else:
                m4 = self._blend_matrix(weight_list, bone_mats)
                pw = G.mat4_transform_point(m4, p)
                mat3 = _mat3_of(m4)
                nw = _mat3_apply(mat3, n)
                verts_mat3.append(mat3)

            u, v = uvs[i][0], uvs[i][1]
            if uv_xform is not None:
                u = uv_xform[0] + u * uv_xform[2]
                v = uv_xform[1] + v * uv_xform[3]
            if self.flip_v:
                v = 1.0 - v

            vertex = P.PmxVertex()
            vertex.position = tf.point(pw)
            vertex.normal = _normalize(tf.normal(nw))
            vertex.uv = (u, v)
            vertex.deform = self._make_deform(weight_list)
            vertex.edge_factor = 1.0
            result.vertices.append(vertex)

        # ---- 索引（颠倒绕序以抵消镜像）----
        if raw_indices is None:
            raw_indices = list(range(count))
        triangles = 0
        for t in range(0, len(raw_indices) - 2, 3):
            a, b, c = raw_indices[t], raw_indices[t + 1], raw_indices[t + 2]
            if a >= count or b >= count or c >= count:
                continue
            if a == b or b == c or a == c:
                continue
            result.indices.append(v_start + a)
            result.indices.append(v_start + c)
            result.indices.append(v_start + b)
            triangles += 1
        result.triangle_count += triangles

        return {
            "node": item["node"],
            "mesh": item["mesh"],
            "prim": item["prim"],
            "material": item["material"],
            "pmx_material": mat_index,
            "v_start": v_start,
            "v_count": count,
            "targets": item["targets"],
            "skin_identity": skin_identity,
            "verts_mat3": verts_mat3,
            "triangles": triangles,
        }

    # -------------------------------------------------- 蒙皮
    def _skin_matrices(self, skin):
        doc = self.doc
        joints = [j for j in (skin.get("joints") or []) if isinstance(j, int)]
        ibm_accessor = skin.get("inverseBindMatrices")
        mats = []
        if ibm_accessor is not None:
            data, comps = doc.accessor_floats(ibm_accessor)
            if comps == 16:
                for k in range(len(joints)):
                    chunk = data[k * 16:(k + 1) * 16]
                    if len(chunk) == 16:
                        mats.append(tuple(float(x) for x in chunk))
                    else:
                        mats.append(G.IDENTITY)
            else:
                mats = [G.IDENTITY] * len(joints)
        else:
            mats = [G.IDENTITY] * len(joints)
        world = [doc.world_matrix(j) for j in joints]
        return joints, [G.mat4_mul(w, ib) for w, ib in zip(world, mats)]

    def _bone_matrix_map(self, skin_joints, skin_mats):
        """PMX 骨骼索引 -> 平均蒙皮矩阵（多关节落到同一骨时取平均）。"""
        groups = {}
        for k, node in enumerate(skin_joints):
            bone = self.bones.node_bone.get(node)
            if bone is None:
                bone = self.bones.bone_for_node(node)
            groups.setdefault(bone, []).append(skin_mats[k])
        out = {}
        for bone, mats in groups.items():
            n = float(len(mats))
            out[bone] = tuple(sum(m[i] for m in mats) / n for i in range(16))
        return out

    def _combine(self, joints, weights, skin_joints, default_bone):
        acc = {}
        for k, w in enumerate(weights):
            if w <= 1e-6:
                continue
            node = None
            if skin_joints and joints[k] < len(skin_joints):
                node = skin_joints[joints[k]]
            bone = self.bones.node_bone.get(node) if node is not None else None
            if bone is None:
                bone = default_bone
            acc[bone] = acc.get(bone, 0.0) + w
        if not acc:
            return [(default_bone, 1.0)]
        items = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_WEIGHTS]
        total = sum(w for _b, w in items)
        if total <= 0:
            return [(default_bone, 1.0)]
        return [(b, w / total) for b, w in items]

    def _blend_matrix(self, weight_list, bone_mats):
        acc = [0.0] * 16
        for bone, w in weight_list:
            m = bone_mats.get(bone)
            if m is None:
                continue
            for i in range(16):
                acc[i] += m[i] * w
        for i in range(16):
            if abs(acc[i]) < 1e-12:
                pass
        # 保证齐次行正确
        acc[15] = 1.0 if abs(acc[15]) < 1e-9 else acc[15]
        return tuple(acc)

    def _make_deform(self, weight_list):
        if not weight_list:
            return P.Bdef1(0)
        if len(weight_list) == 1:
            return P.Bdef1(weight_list[0][0])
        if len(weight_list) == 2:
            return P.Bdef2(weight_list[0][0], weight_list[1][0],
                           float(weight_list[0][1]))
        indices = [b for b, _w in weight_list]
        weights = [float(w) for _b, w in weight_list]
        while len(indices) < 4:
            indices.append(indices[-1])
            weights.append(0.0)
        return P.Bdef4(indices[:4], weights[:4])

    def _compute_normals(self, positions, indices, count):
        acc = [[0.0, 0.0, 0.0] for _ in range(count)]
        if indices:
            for t in range(0, len(indices) - 2, 3):
                a, b, c = indices[t], indices[t + 1], indices[t + 2]
                if a >= count or b >= count or c >= count:
                    continue
                pa, pb, pc = positions[a], positions[b], positions[c]
                ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
                vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
                nx = uy * vz - uz * vy
                ny = uz * vx - ux * vz
                nz = ux * vy - uy * vx
                for idx in (a, b, c):
                    acc[idx][0] += nx
                    acc[idx][1] += ny
                    acc[idx][2] += nz
        return [_normalize(tuple(v)) for v in acc]

    def _uv_transform(self, material_index):
        if material_index is None or material_index < 0:
            return None
        mats = self.doc.json.get("materials") or []
        if material_index >= len(mats):
            return None
        pbr = mats[material_index].get("pbrMetallicRoughness") or {}
        return MAT.texture_transform(self.doc, pbr.get("baseColorTexture"))
