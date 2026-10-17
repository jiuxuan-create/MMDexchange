# -*- coding: utf-8 -*-
"""vrm2pmx —— 把 VRM / glTF 虚拟形象转换成 MMD 可用的 PMX 模型。

纯标准库实现，不依赖 Blender、Unity 或任何第三方转换器。

命令行：
    python -m vrm2pmx 模型.vrm -o 输出目录

图形界面：
    python VRM转PMX.py

Python 调用：
    from vrm2pmx import convert_file, ConversionOptions
    convert_file("模型.vrm", "输出目录", ConversionOptions(unit_scale=12.5))
"""

from . import convert
from .convert import ConversionOptions, ConversionResult, convert_file
from .transform import DEFAULT_UNIT_SCALE

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "convert",           # convert 子模块：convert.convert(...)
    "convert_file",      # 直接调用的函数
    "ConversionOptions",
    "ConversionResult",
    "DEFAULT_UNIT_SCALE",
    "read_vrm_info",
]


def read_vrm_info(vrm_path):
    """只解析不转换，返回 VRM 的文件信息，用于界面/命令行预览。

    返回 dict，键：version / name / authors / humanoid_bones / expressions /
    springs / colliders / meshes / materials / textures / vertices /
    triangles / nodes / extensions。
    """
    from . import gltf as G
    from . import vrm as VRM

    doc = G.read_gltf(vrm_path)
    vrm = VRM.parse_vrm(doc)
    meshes = doc.json.get("meshes") or []
    vertices = 0
    triangles = 0
    for mesh in meshes:
        for prim in mesh.get("primitives") or []:
            attrs = prim.get("attributes") or {}
            if "POSITION" in attrs:
                vertices += int(doc.json["accessors"][attrs["POSITION"]]
                                .get("count") or 0)
            if "indices" in prim:
                count = int(doc.json["accessors"][prim["indices"]]
                            .get("count") or 0)
                triangles += count // 3
    meta = vrm.meta or {}
    authors = meta.get("authors")
    if authors is None:
        authors = [x for x in [meta.get("author")] if x]
    return {
        "version": vrm.version,
        "spec_version": meta.get("specVersion"),
        "name": meta.get("name") or "",
        "authors": list(authors or []),
        "license": meta.get("licenseName") or meta.get("license") or "",
        "humanoid_bones": len(vrm.humanoid_bones),
        "expressions": len(vrm.expressions),
        "springs": len(vrm.springs),
        "colliders": len(vrm.colliders),
        "meshes": len(meshes),
        "materials": len(doc.json.get("materials") or []),
        "textures": len(doc.json.get("images") or []),
        "vertices": vertices,
        "triangles": triangles,
        "nodes": len(doc.json.get("nodes") or []),
        "extensions": list(doc.extensions_used or []),
    }
