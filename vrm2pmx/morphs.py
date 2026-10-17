# -*- coding: utf-8 -*-
"""表情转换：VRM 表情 -> PMX モーフ。

映射原则：
  * VRM 的标准预设尽量落到 MMD 的标准表情名上，
    这样直接用现成的 MMD 动作数据（VMD）就能驱动面部
  * VRM 的注视类表情（lookUp 等）在 MMD 里对应「両目」骨骼，
    但 VRM 侧本身是用顶点偏移实现的，所以如实转成顶点表情，
    命名为「目上/目下/目左/目右」，避免与 MMD 的 眉/口 标准表情撞名
  * 自定义表情原样保留，放在「その他」面板
"""

from . import pmx_model as P

__all__ = ["build_morphs", "PRESET_TO_MMD"]

# VRM 预设名 -> MMD 标准表情名
PRESET_TO_MMD = {
    "blink": "\u307e\u3070\u305f\u304d",           # まばたき
    "blinkLeft": "\u30a6\u30a3\u30f3\u30af",      # ウィンク
    "blinkRight": "\u30a6\u30a3\u30f3\u30af\u53f3",  # ウィンク右
    "aa": "\u3042",
    "ih": "\u3044",
    "ou": "\u3046",
    "ee": "\u3048",
    "oh": "\u304a",
    "happy": "\u7b11\u3044",                       # 笑い
    "angry": "\u6012\u308a",                       # 怒り
    "sad": "\u56f0\u308b",                         # 困る
    "relaxed": "\u306b\u3053\u308a",               # にこり
    "surprised": "\u3073\u3063\u304f\u308a",       # びっくり
}

# 注视类表情：MMD 用 両目 骨骼负责，这里保留数据但不占用标准名
GAZE_TO_MMD = {
    "lookUp": "\u76ee\u4e0a",                     # 目上
    "lookDown": "\u76ee\u4e0b",                   # 目下
    "lookLeft": "\u76ee\u5de6",                   # 目左
    "lookRight": "\u76ee\u53f3",                  # 目右
}

SKIP_PRESETS = ("neutral",)

# 用于材质颜色表情的乘法中性值
_NEUTRAL4 = (1.0, 1.0, 1.0, 1.0)
_NEUTRAL3 = (1.0, 1.0, 1.0)


class _SpanLookup(object):
    def __init__(self, mesh_result, doc, transform):
        self.spans = mesh_result.spans
        self.doc = doc
        self.tf = transform
        self.by_node = {}
        self.by_mesh = {}
        for span in self.spans:
            self.by_node.setdefault(span["node"], []).append(span)
            self.by_mesh.setdefault(span["mesh"], []).append(span)
        self._cache = {}

    def deltas(self, span_key, span, target_index):
        key = (span_key, target_index)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        out = []
        targets = span["targets"]
        if target_index < len(targets):
            accessor = targets[target_index].get("POSITION")
            if accessor is not None:
                raw, comps = self.doc.accessor_vec(accessor, 3)
                count = min(len(raw), span["v_count"])
                mat3_list = span.get("verts_mat3")
                identity = span["skin_identity"]
                start = span["v_start"]
                for k in range(count):
                    d = raw[k]
                    if abs(d[0]) < 1e-9 and abs(d[1]) < 1e-9 and abs(d[2]) < 1e-9:
                        continue
                    if not identity and mat3_list is not None and k < len(mat3_list):
                        a = mat3_list[k]
                        d = (a[0] * d[0] + a[1] * d[1] + a[2] * d[2],
                             a[3] * d[0] + a[4] * d[1] + a[5] * d[2],
                             a[6] * d[0] + a[7] * d[1] + a[8] * d[2])
                    out.append((start + k, self.tf.delta(d)))
        self._cache[key] = out
        return out


def build_morphs(vrm, mesh_result, bones, transform, options=None):
    options = options or {}
    doc = vrm.doc
    lookup = _SpanLookup(mesh_result, doc, transform)
    morphs = []
    warnings = []
    used_names = set()

    # ---- 顶点表情 ----
    for expr in vrm.expressions:
        preset = expr.preset or ""
        if preset in SKIP_PRESETS:
            continue
        if preset in PRESET_TO_MMD:
            name = PRESET_TO_MMD[preset]
            panel = _panel_of(name)
        elif preset in GAZE_TO_MMD:
            name = GAZE_TO_MMD[preset]
            panel = P.PANEL_EYE
        else:
            name = expr.name or "expression"
            panel = P.PANEL_OTHER
        name = _unique(name, used_names)

        acc = {}
        for (target_ref, target_index, weight) in expr.morph_binds:
            if weight == 0.0:
                continue
            spans = (lookup.by_node.get(target_ref) if vrm.version == 1
                     else lookup.by_mesh.get(target_ref)) or []
            for span in spans:
                key = (span["node"], span["prim"])
                for vertex_index, delta in lookup.deltas(key, span, target_index):
                    cur = acc.get(vertex_index)
                    if cur is None:
                        acc[vertex_index] = [delta[0] * weight, delta[1] * weight,
                                             delta[2] * weight]
                    else:
                        cur[0] += delta[0] * weight
                        cur[1] += delta[1] * weight
                        cur[2] += delta[2] * weight

        if not acc:
            continue

        morph = P.PmxMorph()
        morph.name = name
        morph.english_name = preset or name
        morph.panel = panel
        morph.morph_type = P.MORPH_VERTEX
        for vertex_index in sorted(acc):
            offset = acc[vertex_index]
            if (abs(offset[0]) < 1e-9 and abs(offset[1]) < 1e-9
                    and abs(offset[2]) < 1e-9):
                continue
            morph.offsets.append(P.MorphVertexOffset(vertex_index, tuple(offset)))
        if morph.offsets:
            morphs.append(morph)

        # ---- 该表情的材质颜色变化 ----
        mat_morph = _material_morph(vrm, expr, mesh_result, name)
        if mat_morph is not None:
            morphs.append(mat_morph)

    # ---- 4 个顶点表情上限检查 ----
    touch = {}
    for morph in morphs:
        if morph.morph_type != P.MORPH_VERTEX:
            continue
        for off in morph.offsets:
            touch[off.index] = touch.get(off.index, 0) + 1
    over = sum(1 for v in touch.values() if v > 4)
    if over:
        warnings.append(
            "有 %d 个顶点被超过 4 个顶点表情同时影响，MMD 只会取前 4 个，"
            "多出来的表情在极端组合下可能不生效。" % over)

    if not morphs:
        warnings.append("该模型没有任何表情，转换后的 PMX 也没有表情。")
    return morphs, warnings


def _material_morph(vrm, expr, mesh_result, name):
    if not expr.material_binds:
        return None
    mapping = mesh_result.gltf_material_to_pmx
    name_to_index = {}
    for i, mat in enumerate(vrm.doc.json.get("materials") or []):
        name_to_index[mat.get("name")] = i

    offsets = []
    for bind in expr.material_binds:
        target, prop, value, _raw = bind
        if isinstance(target, str):
            gltf_index = name_to_index.get(target)
            kind = "color" if prop in ("_Color", "_BaseColor") else "other"
            color = None
            if kind == "color" and isinstance(value, (list, tuple)):
                color = value
        else:
            gltf_index = target
            kind = prop
            color = value if kind == "color" else None
        if gltf_index is None or gltf_index not in mapping:
            continue
        if kind != "color" or not color:
            continue
        rgba = tuple(float(v) for v in list(color)[:4])
        while len(rgba) < 4:
            rgba = rgba + (1.0,)
        offset = P.MorphMaterialOffset(mapping[gltf_index], calc_mode=0,
                                       diffuse=rgba,
                                       specular=_NEUTRAL3, specular_factor=1.0,
                                       ambient=_NEUTRAL3, edge_color=_NEUTRAL4,
                                       edge_size=1.0,
                                       texture_factor=_NEUTRAL4,
                                       sphere_texture_factor=_NEUTRAL4,
                                       toon_texture_factor=_NEUTRAL4)
        offsets.append(offset)
    if not offsets:
        return None
    morph = P.PmxMorph()
    morph.name = name
    morph.english_name = ""
    morph.panel = P.PANEL_OTHER
    morph.morph_type = P.MORPH_MATERIAL
    morph.offsets = offsets
    return morph


def _panel_of(name):
    from .mmd_bones import panel_of_morph_name
    return panel_of_morph_name(name)


def _unique(name, used):
    if name not in used:
        used.add(name)
        return name
    i = 2
    while "%s_%d" % (name, i) in used:
        i += 1
    final = "%s_%d" % (name, i)
    used.add(final)
    return final
