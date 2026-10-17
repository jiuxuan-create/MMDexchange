# -*- coding: utf-8 -*-
"""VRM 结构查看器（开发 / 排障用）。

用法：
    python tools/inspect_vrm.py <模型.vrm>

输出：VRM 版本、humanoid 骨骼、表情、SpringBone、材质（MToon）、网格与属性、
贴图等信息，用于确认转换前的前提条件是否齐备。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vrm2pmx import gltf as G  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    doc = G.read_gltf(path)
    print("文件:", path)
    print("文档:", doc)
    print("extensionsUsed   :", doc.extensions_used)
    print("extensionsRequired:", doc.json.get("extensionsRequired", []))

    exts = doc.json.get("extensions", {})
    vrm0 = exts.get("VRM")
    vrm1 = exts.get("VRMC_vrm")
    print("VRM 0.x 扩展:", "有" if vrm0 else "无")
    print("VRM 1.0 扩展:", "有" if vrm1 else "无")
    if vrm0:
        print("  VRM 0.x 版本字段:", vrm0.get("specVersion"), " exporter:", vrm0.get("exporter"))
    if vrm1:
        print("  VRM 1.0 specVersion:", vrm1.get("specVersion"))

    # humanoid
    bones = {}
    if vrm0:
        for hb in vrm0.get("humanoid", {}).get("humanBones", []):
            bones[hb.get("bone")] = hb.get("node")
    if vrm1:
        for name, info in (vrm1.get("humanoid", {}).get("humanBones") or {}).items():
            bones[name] = (info or {}).get("node")
    print("\n=== humanoid 骨骼 (%d) ===" % len(bones))
    for name in sorted(bones):
        node = bones[name]
        pos = doc.world_translation(node) if isinstance(node, int) else None
        print("  %-18s node=%-5s 世界坐标=%s" % (
            name, node,
            "(%.4f, %.4f, %.4f)" % pos if pos else "-"))

    # 表情
    print("\n=== 表情 ===")
    if vrm0:
        groups = vrm0.get("blendShapeMaster", {}).get("blendShapeGroups", [])
        print("  VRM 0.x blendShapeGroups:", len(groups))
        for g in groups[:40]:
            print("    %-14s preset=%-14s binds=%d"
                  % (g.get("name"), g.get("presetName"), len(g.get("binds", []))))
    if vrm1:
        ex = (vrm1.get("expressions") or {})
        preset = ex.get("preset") or {}
        custom = ex.get("custom") or {}
        print("  VRM 1.0 preset:", len(preset), " custom:", len(custom))
        for name in sorted(preset):
            v = preset[name] or {}
            print("    %-14s morphBinds=%d materialBinds=%d binary=%s"
                  % (name, len(v.get("morphTargetBinds") or []),
                     len(v.get("materialColorBinds") or []), v.get("isBinary")))

    # SpringBone
    print("\n=== 物理 (SpringBone) ===")
    if vrm0:
        sa = vrm0.get("secondaryAnimation", {}) or {}
        print("  VRM 0.x boneGroups:", len(sa.get("boneGroups", [])),
              " colliderGroups:", len(sa.get("colliderGroups", [])))
        for i, g in enumerate(sa.get("boneGroups", [])[:40]):
            print("    [%d] %-14s bones=%d stiff=%.2f drag=%.2f grav=%.2f hitR=%.3f "
                  "colliderGroups=%s"
                  % (i, (g.get("comment") or "")[:14], len(g.get("bones", [])),
                     g.get("stiffiness", 0), g.get("dragForce", 0),
                     g.get("gravityPower", 0), g.get("hitRadius", 0),
                     g.get("colliderGroups")))
    if vrm1:
        sb = exts.get("VRMC_springBone", {}) or {}
        print("  VRM 1.0 springs:", len(sb.get("springs", [])),
              " colliders:", len(sb.get("colliders", [])),
              " colliderGroups:", len(sb.get("colliderGroups", [])))
        for i, s in enumerate(sb.get("springs", [])[:40]):
            print("    [%d] %-14s joints=%d" % (i, (s.get("name") or "")[:14],
                                                len(s.get("joints", []))))
        for i, c in enumerate(sb.get("colliders", [])[:10]):
            shape = c.get("shape") or {}
            kind = "sphere" if "sphere" in shape else ("capsule" if "capsule" in shape
                                                       else "?")
            print("    collider[%d] node=%s 形状=%s %s"
                  % (i, c.get("node"), kind, shape.get(kind)))

    # 网格
    print("\n=== 网格 ===")
    meshes = doc.json.get("meshes", [])
    print("  mesh 数:", len(meshes), " skin 数:", len(doc.json.get("skins", [])))
    total_v = 0
    total_tri = 0
    attr_keys = {}
    target_total = 0
    for mi, mesh in enumerate(meshes):
        for pi, prim in enumerate(mesh.get("primitives", [])):
            attrs = prim.get("attributes", {})
            for k in attrs:
                attr_keys[k] = attr_keys.get(k, 0) + 1
            vcount = doc.json["accessors"][attrs["POSITION"]]["count"]
            total_v += vcount
            if "indices" in prim:
                total_tri += doc.json["accessors"][prim["indices"]]["count"] // 3
            targets = prim.get("targets") or []
            target_total += len(targets)
            print("    mesh[%d].prim[%d] 顶点=%d 材质=%s 属性=%s targets=%d mode=%s"
                  % (mi, pi, vcount, prim.get("material"), sorted(attrs),
                     len(targets), prim.get("mode", 4)))
    print("  合计顶点:", total_v, " 三角面:", total_tri, " morph target 条目:", target_total)
    print("  出现过的属性:", sorted(attr_keys))

    # 材质
    print("\n=== 材质 (%d) ===" % len(doc.json.get("materials", [])))
    for i, mat in enumerate(doc.json.get("materials", [])):
        me = (mat.get("extensions") or {})
        pbr = mat.get("pbrMetallicRoughness", {})
        print("  [%2d] %-22s doubleSided=%s alphaMode=%s baseTex=%s ext=%s"
              % (i, (mat.get("name") or "")[:22], mat.get("doubleSided"),
                 mat.get("alphaMode"),
                 (pbr.get("baseColorTexture") or {}).get("index"),
                 sorted(me)))
        if "VRMC_materials_mtoon" in me:
            mt = me["VRMC_materials_mtoon"]
            print("        MToon: %s" % sorted(
                k for k in mt if k not in ("extensions", "extras")))

    print("\n=== 贴图 (%d) ===" % len(doc.json.get("images", [])))
    for i, img in enumerate(doc.json.get("images", [])):
        print("  [%2d] name=%s mime=%s uri=%s bufferView=%s"
              % (i, img.get("name"), img.get("mimeType"),
                 (img.get("uri") or "")[:40], img.get("bufferView")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
