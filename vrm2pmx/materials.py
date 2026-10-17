# -*- coding: utf-8 -*-
"""材质与贴图转换：glTF / MToon -> PMX 材质 + 贴图文件。"""

import os

from . import pmx_model as P

__all__ = ["TexturePool", "build_materials", "KHR_TEXTURE_TRANSFORM"]

KHR_TEXTURE_TRANSFORM = "KHR_texture_transform"

# VRM 0.x 里可能出现的球面/描画贴图键名
SPHERE_KEYS = ("_SphereTexture", "_SphereAdd", "_SphereTex", "sphereTexture",
               "_MatCap", "matcap", "_Sphere")

DEFAULT_TOON_INDEX = 0


class TexturePool(object):
    """把 glTF 的 image 落盘成 PMX 贴图，并维护 image -> PMX 纹理索引 的映射。"""

    def __init__(self, doc, out_dir, tex_dirname="tex"):
        self.doc = doc
        self.out_dir = out_dir
        self.tex_dirname = tex_dirname
        self.paths = []                 # PMX 纹理路径（反斜杠相对路径）
        self.image_to_index = {}
        self.written = []               # (相对路径, 绝对路径, 字节数)
        self.warnings = []

    def index_of_image(self, image_index, hint=""):
        if image_index is None or image_index < 0:
            return -1
        if image_index in self.image_to_index:
            return self.image_to_index[image_index]
        try:
            data, ext = self.doc.image_bytes(image_index)
        except Exception as exc:
            self.warnings.append("贴图 image[%s] 读取失败：%s" % (image_index, exc))
            return -1
        safe_hint = _safe_name(hint) or "img"
        filename = "%03d_%s%s" % (image_index, safe_hint, ext)
        rel = "%s\\%s" % (self.tex_dirname, filename)
        abs_dir = os.path.join(self.out_dir, self.tex_dirname)
        os.makedirs(abs_dir, exist_ok=True)
        abs_path = os.path.join(abs_dir, filename)
        with open(abs_path, "wb") as fh:
            fh.write(data)
        idx = len(self.paths)
        self.paths.append(rel)
        self.image_to_index[image_index] = idx
        self.written.append((rel, abs_path, len(data)))
        return idx


def _safe_name(name):
    out = []
    for ch in (name or ""):
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        elif ch in " ":
            out.append("_")
    return "".join(out)[:24]


def _tex_index(doc, texture_info):
    """textureInfo -> image 索引。"""
    if not texture_info:
        return None
    index = texture_info.get("index")
    if index is None:
        return None
    textures = doc.json.get("textures") or []
    if index >= len(textures):
        return None
    return textures[index].get("source")


def texture_transform(doc, texture_info):
    """取出 KHR_texture_transform 的 (offset_u, offset_v, scale_u, scale_v)，没有则 None。"""
    if not texture_info:
        return None
    ext = (texture_info.get("extensions") or {}).get(KHR_TEXTURE_TRANSFORM)
    if not ext:
        return None
    offset = ext.get("offset") or (0.0, 0.0)
    scale = ext.get("scale") or (1.0, 1.0)
    if "rotation" in ext and abs(float(ext["rotation"])) > 1e-9:
        return None
    return (float(offset[0]), float(offset[1]), float(scale[0]), float(scale[1]))


def _mtoon_params(vrm, material_index):
    return vrm.mtoon_materials.get(material_index) or {}


def _lookup(mtoon, *keys):
    for k in keys:
        if k in mtoon:
            return mtoon[k]
    return None


def build_materials(vrm, textures, options=None, used=None):
    """返回 (PmxMaterial 列表, {glTF 材质索引: PMX 材质索引})。

    used 为实际被网格用到的 glTF 材质索引集合；未被用到的材质不输出，
    避免生成一堆 index_count=0 的空材质。
    """
    options = options or {}
    doc = vrm.doc
    gltf_materials = doc.json.get("materials") or []
    out = []
    mapping = {}
    warnings = []

    default_uv = (1.0, 1.0, 1.0, 1.0)
    default_edge = options.get("edge", True)

    for i, gm in enumerate(gltf_materials):
        if used is not None and i not in used:
            continue
        pbr = gm.get("pbrMetallicRoughness") or {}
        base = pbr.get("baseColorFactor") or (1.0, 1.0, 1.0, 1.0)
        base = tuple(float(v) for v in base)
        alpha_mode = gm.get("alphaMode", "OPAQUE")
        double_sided = bool(gm.get("doubleSided"))
        mtoon = _mtoon_params(vrm, i)

        mat = P.PmxMaterial()
        mat.name = (gm.get("name") or ("material_%d" % i))[:50]
        mat.english_name = mat.name[:50]

        # MToon 的 litColor 优先于 baseColorFactor
        lit = _lookup(mtoon, "litColor", "_Color")
        if isinstance(lit, (list, tuple)) and len(lit) >= 3:
            base = (float(lit[0]), float(lit[1]), float(lit[2]),
                    float(lit[3]) if len(lit) > 3 else base[3])

        diffuse = list(base)
        if alpha_mode == "MASK":
            diffuse[3] = 1.0
        mat.diffuse = tuple(diffuse)

        # 環境色：优先用 MToon 的暗部颜色，否则用中性灰
        shade = _lookup(mtoon, "shadeColor", "_ShadeColor")
        if isinstance(shade, (list, tuple)) and len(shade) >= 3:
            mat.ambient = (float(shade[0]), float(shade[1]), float(shade[2]))
        else:
            mat.ambient = (0.5, 0.5, 0.5)

        # 基础贴图
        uv_xform = default_uv
        tex_index = -1
        if "baseColorTexture" in pbr:
            info = pbr["baseColorTexture"]
            tex_index = textures.index_of_image(_tex_index(doc, info), mat.name)
            found = texture_transform(doc, info)
            if found:
                uv_xform = found
        mat.texture_index = tex_index

        # 球面贴图（MToon 的 MatCap / sphere）
        for key in SPHERE_KEYS:
            info = (gm.get("extensions") or {}).get(key)
            if not isinstance(info, dict):
                info = (mtoon.get("textureProperties") or {}).get(key)
            if isinstance(info, dict) and "index" in info:
                sphere = textures.index_of_image(_tex_index(doc, info), mat.name + "_sph")
                if sphere >= 0:
                    mat.sphere_texture_index = sphere
                    mat.sphere_mode = P.SPHERE_ADD
                break

        mat.toon_sharing_flag = 1
        mat.toon_texture_index = DEFAULT_TOON_INDEX

        flag = P.MATERIALFLAG_GROUNDSHADOW | P.MATERIALFLAG_SELFSHADOWMAP \
            | P.MATERIALFLAG_SELFSHADOW
        if double_sided:
            flag |= P.MATERIALFLAG_BOTHFACE
        if default_edge and alpha_mode != "BLEND":
            flag |= P.MATERIALFLAG_EDGE
        mat.flag = flag

        outline = _lookup(mtoon, "outlineColor")
        if isinstance(outline, (list, tuple)) and len(outline) >= 3:
            mat.edge_color = (float(outline[0]), float(outline[1]), float(outline[2]),
                              1.0)
        else:
            mat.edge_color = (0.0, 0.0, 0.0, 1.0)
        mat.edge_size = float(options.get("edge_size", 1.0))
        mat.specular = (0.0, 0.0, 0.0)
        mat.specular_factor = 0.0
        mat.comment = "%s -> PMX (vrm2pmx)" % (gm.get("name") or ("material_%d" % i))

        out.append(mat)
        mapping[i] = len(out) - 1

    if not out:
        # 一个材质都没有的模型，补一个默认材质
        mat = P.PmxMaterial()
        mat.name = "material"
        mat.english_name = "material"
        mat.diffuse = (1.0, 1.0, 1.0, 1.0)
        mat.ambient = (0.5, 0.5, 0.5)
        out.append(mat)
        mapping[-1] = 0

    # 有 primitive 没写材质定义时才补兜底材质，避免产出空的 index_count=0 材质
    if -1 not in mapping and (used is None or -1 in used):
        mat = P.PmxMaterial()
        mat.name = "(no material)"
        mat.english_name = "no material"
        mat.ambient = (0.5, 0.5, 0.5)
        out.append(mat)
        mapping[-1] = len(out) - 1

    return out, mapping
