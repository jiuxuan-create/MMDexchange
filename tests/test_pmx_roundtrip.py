# -*- coding: utf-8 -*-
"""PMX 读写往返测试。

用真实的复杂 PMX 模型走一遍 读 -> 写 -> 再读，逐字段比对，
确认写出器不会丢数据或写错结构。

用法：
    python tests/test_pmx_roundtrip.py <模型.pmx> [更多模型...]
    python tests/test_pmx_roundtrip.py            # 自动找参考模型
"""

import os
import sys
import tempfile
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)

from vrm2pmx import pmx_model as P  # noqa: E402
from sample_paths import find_ref_pmx  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FLOAT_TOL = 1e-5


def _vec(v):
    """把 pymeshio 的 Vector3 / Vector2 或元组统一成元组。"""
    if hasattr(v, "x"):
        return (v.x, v.y, v.z) if hasattr(v, "z") else (v.x, v.y)
    return tuple(v)


def default_candidates():
    """没传命令行参数时自动找参考模型（见 tests/sample_paths.py 的说明）。"""
    path = find_ref_pmx()
    return [path] if path else []


class Checker(object):
    def __init__(self):
        self.failures = []
        self.checks = 0

    def eq(self, label, a, b):
        self.checks += 1
        if a != b:
            self.failures.append("%s: %r != %r" % (label, a, b))

    def close(self, label, a, b, tol=FLOAT_TOL):
        self.checks += 1
        if abs(float(a) - float(b)) > tol:
            self.failures.append("%s: %r != %r (tol %g)" % (label, a, b, tol))

    def seq_close(self, label, a, b, tol=FLOAT_TOL):
        self.checks += 1
        if len(a) != len(b):
            self.failures.append("%s: 长度 %d != %d" % (label, len(a), len(b)))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            if abs(float(x) - float(y)) > tol:
                self.failures.append("%s[%d]: %r != %r" % (label, i, x, y))
                return


def compare(a, b):
    c = Checker()
    c.close("version", a.version, b.version)
    c.eq("text_encoding", a.text_encoding, b.text_encoding)
    c.eq("additional_uv_count", a.additional_uv_count, b.additional_uv_count)
    c.eq("name", a.name, b.name)
    c.eq("english_name", a.english_name, b.english_name)
    c.eq("comment", a.comment, b.comment)
    c.eq("english_comment", a.english_comment, b.english_comment)

    c.eq("vertex count", len(a.vertices), len(b.vertices))
    if len(a.vertices) == len(b.vertices):
        for i, (va, vb) in enumerate(zip(a.vertices, b.vertices)):
            c.seq_close("v[%d].position" % i, va.position, vb.position)
            c.seq_close("v[%d].normal" % i, va.normal, vb.normal)
            c.seq_close("v[%d].uv" % i, va.uv, vb.uv, 1e-6)
            c.close("v[%d].edge" % i, va.edge_factor, vb.edge_factor)
            if len(va.additional_uv) != len(vb.additional_uv):
                c.failures.append("v[%d] 追加UV层数不一致" % i)
            else:
                for k, (ua, ub) in enumerate(zip(va.additional_uv, vb.additional_uv)):
                    c.seq_close("v[%d].adduv%d" % (i, k), ua, ub, 1e-6)
            c.eq("v[%d].deform.kind" % i, va.deform.kind, vb.deform.kind)
            if va.deform.kind == P.DEFORM_BDEF1:
                c.eq("v[%d].bone0" % i, va.deform.index0, vb.deform.index0)
            elif va.deform.kind == P.DEFORM_BDEF2:
                c.eq("v[%d].bone0" % i, va.deform.index0, vb.deform.index0)
                c.eq("v[%d].bone1" % i, va.deform.index1, vb.deform.index1)
                c.close("v[%d].w0" % i, va.deform.weight0, vb.deform.weight0)
            elif va.deform.kind in (P.DEFORM_BDEF4, P.DEFORM_QDEF):
                c.eq("v[%d].bones" % i, va.deform.indices, vb.deform.indices)
                c.seq_close("v[%d].weights" % i, va.deform.weights, vb.deform.weights)
            elif va.deform.kind == P.DEFORM_SDEF:
                c.eq("v[%d].sdef idx" % i, (va.deform.index0, va.deform.index1),
                     (vb.deform.index0, vb.deform.index1))
                c.close("v[%d].sdef w" % i, va.deform.weight0, vb.deform.weight0)
                c.seq_close("v[%d].sdef c" % i, va.deform.c, vb.deform.c)
                c.seq_close("v[%d].sdef r0" % i, va.deform.r0, vb.deform.r0)
                c.seq_close("v[%d].sdef r1" % i, va.deform.r1, vb.deform.r1)

    c.eq("index count", len(a.indices), len(b.indices))
    if len(a.indices) == len(b.indices):
        c.eq("indices", a.indices, b.indices)

    c.eq("textures", a.textures, b.textures)

    c.eq("material count", len(a.materials), len(b.materials))
    for i, (ma, mb) in enumerate(zip(a.materials, b.materials)):
        c.eq("m[%d].name" % i, ma.name, mb.name)
        c.eq("m[%d].en" % i, ma.english_name, mb.english_name)
        c.seq_close("m[%d].diffuse" % i, ma.diffuse, mb.diffuse, 1e-6)
        c.seq_close("m[%d].specular" % i, ma.specular, mb.specular, 1e-6)
        c.close("m[%d].specfac" % i, ma.specular_factor, mb.specular_factor)
        c.seq_close("m[%d].ambient" % i, ma.ambient, mb.ambient, 1e-6)
        c.eq("m[%d].flag" % i, ma.flag, mb.flag)
        c.seq_close("m[%d].edge_color" % i, ma.edge_color, mb.edge_color, 1e-6)
        c.close("m[%d].edge_size" % i, ma.edge_size, mb.edge_size)
        c.eq("m[%d].tex" % i, ma.texture_index, mb.texture_index)
        c.eq("m[%d].sph" % i, ma.sphere_texture_index, mb.sphere_texture_index)
        c.eq("m[%d].sphmode" % i, ma.sphere_mode, mb.sphere_mode)
        c.eq("m[%d].toonshare" % i, ma.toon_sharing_flag, mb.toon_sharing_flag)
        c.eq("m[%d].toon" % i, ma.toon_texture_index, mb.toon_texture_index)
        c.eq("m[%d].comment" % i, ma.comment, mb.comment)
        c.eq("m[%d].index_count" % i, ma.index_count, mb.index_count)

    c.eq("bone count", len(a.bones), len(b.bones))
    for i, (ba, bb) in enumerate(zip(a.bones, b.bones)):
        c.eq("b[%d].name" % i, ba.name, bb.name)
        c.eq("b[%d].en" % i, ba.english_name, bb.english_name)
        c.seq_close("b[%d].pos" % i, ba.position, bb.position)
        c.eq("b[%d].parent" % i, ba.parent_index, bb.parent_index)
        c.eq("b[%d].layer" % i, ba.layer, bb.layer)
        c.eq("b[%d].flag" % i, ba.flag, bb.flag)
        c.eq("b[%d].tailsbone" % i, ba.tail_is_bone, bb.tail_is_bone)
        if ba.tail_is_bone:
            c.eq("b[%d].tail_index" % i, ba.tail_index, bb.tail_index)
        else:
            c.seq_close("b[%d].tail_pos" % i, ba.tail_position, bb.tail_position)
        if ba.has_append:
            c.eq("b[%d].effect" % i, ba.effect_index, bb.effect_index)
            c.close("b[%d].factor" % i, ba.effect_factor, bb.effect_factor)
        if ba.flag & P.BONEFLAG_HAS_FIXED_AXIS:
            c.seq_close("b[%d].fixed" % i, ba.fixed_axis, bb.fixed_axis)
        if ba.flag & P.BONEFLAG_HAS_LOCAL_AXIS:
            c.seq_close("b[%d].localx" % i, ba.local_x_axis, bb.local_x_axis)
            c.seq_close("b[%d].localz" % i, ba.local_z_axis, bb.local_z_axis)
        if ba.flag & P.BONEFLAG_IS_EXTERNAL_PARENT_DEFORM:
            c.eq("b[%d].extkey" % i, ba.external_key, bb.external_key)
        c.eq("b[%d].is_ik" % i, ba.is_ik, bb.is_ik)
        if ba.is_ik and bb.is_ik:
            c.eq("b[%d].ik.target" % i, ba.ik.target_index, bb.ik.target_index)
            c.eq("b[%d].ik.loop" % i, ba.ik.loop, bb.ik.loop)
            c.close("b[%d].ik.limit" % i, ba.ik.limit_radian, bb.ik.limit_radian)
            c.eq("b[%d].ik.links" % i, len(ba.ik.links), len(bb.ik.links))
            for k, (la, lb) in enumerate(zip(ba.ik.links, bb.ik.links)):
                c.eq("b[%d].ik.link%d" % (i, k), la.bone_index, lb.bone_index)
                c.eq("b[%d].ik.link%d.limit" % (i, k), la.limit_angle, lb.limit_angle)
                if la.limit_angle:
                    c.seq_close("b[%d].ik.link%d.min" % (i, k), la.limit_min, lb.limit_min)
                    c.seq_close("b[%d].ik.link%d.max" % (i, k), la.limit_max, lb.limit_max)

    c.eq("morph count", len(a.morphs), len(b.morphs))
    for i, (ma, mb) in enumerate(zip(a.morphs, b.morphs)):
        c.eq("mo[%d].name" % i, ma.name, mb.name)
        c.eq("mo[%d].en" % i, ma.english_name, mb.english_name)
        c.eq("mo[%d].panel" % i, ma.panel, mb.panel)
        c.eq("mo[%d].type" % i, ma.morph_type, mb.morph_type)
        c.eq("mo[%d].offsets" % i, len(ma.offsets), len(mb.offsets))
        for k, (oa, ob) in enumerate(zip(ma.offsets, mb.offsets)):
            tag = "mo[%d].off%d" % (i, k)
            c.eq(tag + ".index", oa.index, ob.index)
            if ma.morph_type == P.MORPH_GROUP:
                c.close(tag + ".ratio", oa.ratio, ob.ratio)
            elif ma.morph_type == P.MORPH_VERTEX:
                c.seq_close(tag + ".offset", oa.offset, ob.offset)
            elif ma.morph_type == P.MORPH_BONE:
                c.seq_close(tag + ".trans", oa.translation, ob.translation)
                c.seq_close(tag + ".rot", oa.rotation, ob.rotation)
            elif ma.morph_type in (P.MORPH_UV, P.MORPH_UV1, P.MORPH_UV2,
                                   P.MORPH_UV3, P.MORPH_UV4):
                c.seq_close(tag + ".uv", oa.offset, ob.offset)
            elif ma.morph_type == P.MORPH_MATERIAL:
                c.eq(tag + ".calc", oa.calc_mode, ob.calc_mode)
                c.seq_close(tag + ".diffuse", oa.diffuse, ob.diffuse, 1e-6)
                c.close(tag + ".specfac", oa.specular_factor, ob.specular_factor)
                c.seq_close(tag + ".edge", oa.edge_color, ob.edge_color, 1e-6)
                c.close(tag + ".edgesize", oa.edge_size, ob.edge_size)
                c.seq_close(tag + ".texfac", oa.texture_factor, ob.texture_factor, 1e-6)
            elif ma.morph_type == P.MORPH_FLIP:
                c.close(tag + ".ratio", oa.ratio, ob.ratio)
            elif ma.morph_type == P.MORPH_IMPULSE:
                c.eq(tag + ".local", oa.local_flag, ob.local_flag)
                c.seq_close(tag + ".vel", oa.velocity, ob.velocity)
                c.seq_close(tag + ".torque", oa.torque, ob.torque)

    c.eq("display count", len(a.display_slots), len(b.display_slots))
    for i, (sa, sb) in enumerate(zip(a.display_slots, b.display_slots)):
        c.eq("d[%d].name" % i, sa.name, sb.name)
        c.eq("d[%d].en" % i, sa.english_name, sb.english_name)
        c.eq("d[%d].special" % i, sa.special_flag, sb.special_flag)
        c.eq("d[%d].refs" % i, sa.references, sb.references)

    c.eq("rigidbody count", len(a.rigidbodies), len(b.rigidbodies))
    for i, (ra, rb) in enumerate(zip(a.rigidbodies, b.rigidbodies)):
        c.eq("rb[%d].name" % i, ra.name, rb.name)
        c.eq("rb[%d].bone" % i, ra.bone_index, rb.bone_index)
        c.eq("rb[%d].group" % i, ra.collision_group, rb.collision_group)
        c.eq("rb[%d].nocol" % i, ra.no_collision_group, rb.no_collision_group)
        c.eq("rb[%d].shape" % i, ra.shape_type, rb.shape_type)
        c.seq_close("rb[%d].size" % i, ra.shape_size, rb.shape_size)
        c.seq_close("rb[%d].pos" % i, ra.shape_position, rb.shape_position)
        c.seq_close("rb[%d].rot" % i, ra.shape_rotation, rb.shape_rotation)
        c.close("rb[%d].mass" % i, ra.mass, rb.mass)
        c.close("rb[%d].linD" % i, ra.linear_damping, rb.linear_damping)
        c.close("rb[%d].angD" % i, ra.angular_damping, rb.angular_damping)
        c.close("rb[%d].rest" % i, ra.restitution, rb.restitution)
        c.close("rb[%d].fric" % i, ra.friction, rb.friction)
        c.eq("rb[%d].mode" % i, ra.mode, rb.mode)

    c.eq("joint count", len(a.joints), len(b.joints))
    for i, (ja, jb) in enumerate(zip(a.joints, b.joints)):
        c.eq("j[%d].name" % i, ja.name, jb.name)
        c.eq("j[%d].type" % i, ja.joint_type, jb.joint_type)
        c.eq("j[%d].a" % i, ja.rigidbody_index_a, jb.rigidbody_index_a)
        c.eq("j[%d].b" % i, ja.rigidbody_index_b, jb.rigidbody_index_b)
        c.seq_close("j[%d].pos" % i, ja.position, jb.position)
        c.seq_close("j[%d].rot" % i, ja.rotation, jb.rotation)
        c.seq_close("j[%d].tmin" % i, ja.translation_limit_min, jb.translation_limit_min)
        c.seq_close("j[%d].tmax" % i, ja.translation_limit_max, jb.translation_limit_max)
        c.seq_close("j[%d].rmin" % i, ja.rotation_limit_min, jb.rotation_limit_min)
        c.seq_close("j[%d].rmax" % i, ja.rotation_limit_max, jb.rotation_limit_max)
        c.seq_close("j[%d].spT" % i, ja.spring_constant_translation,
                    jb.spring_constant_translation)
        c.seq_close("j[%d].spR" % i, ja.spring_constant_rotation,
                    jb.spring_constant_rotation)

    return c


def crosscheck_with_pymeshio(path, model):
    """把额外UV剥掉后写出，交给 pymeshio（独立实现）读一遍，交叉验证结构。"""
    try:
        from pymeshio.pmx import reader as pymeshio_reader
    except Exception as exc:
        print("    [跳过] 未安装 pymeshio: %s" % exc)
        return None

    stripped = P.read_pmx(path)
    for v in stripped.vertices:
        v.additional_uv = []
    stripped.additional_uv_count = 0

    tmp = os.path.join(tempfile.gettempdir(), "_roundtrip_nouv.pmx")
    P.write_pmx(tmp, stripped)
    try:
        ext = pymeshio_reader.read_from_file(tmp)
    except Exception as exc:
        print("    [失败] pymeshio 无法读取我方写出的 PMX: %s" % exc)
        traceback.print_exc()
        return False

    c = Checker()
    c.eq("pymeshio: name", ext.name, model.name)
    c.eq("pymeshio: vertex count", len(ext.vertices), len(model.vertices))
    c.eq("pymeshio: index count", len(ext.indices), len(model.indices))
    c.eq("pymeshio: texture count", len(ext.textures), len(model.textures))
    c.eq("pymeshio: material count", len(ext.materials), len(model.materials))
    c.eq("pymeshio: bone count", len(ext.bones), len(model.bones))
    c.eq("pymeshio: morph count", len(ext.morphs), len(model.morphs))
    c.eq("pymeshio: display count", len(ext.display_slots), len(model.display_slots))
    c.eq("pymeshio: rigidbody count", len(ext.rigidbodies), len(model.rigidbodies))
    c.eq("pymeshio: joint count", len(ext.joints), len(model.joints))
    c.eq("pymeshio: indices", list(ext.indices), list(model.indices))
    c.eq("pymeshio: textures", list(ext.textures), list(model.textures))
    if len(ext.bones) == len(model.bones):
        for i, (ba, bb) in enumerate(zip(ext.bones, model.bones)):
            c.eq("pymeshio: b[%d].name" % i, ba.name, bb.name)
            c.eq("pymeshio: b[%d].parent" % i, ba.parent_index, bb.parent_index)
            c.seq_close("pymeshio: b[%d].pos" % i, _vec(ba.position), bb.position)
    if len(ext.vertices) == len(model.vertices):
        for i, (va, vb) in enumerate(zip(ext.vertices, model.vertices)):
            c.seq_close("pymeshio: v[%d].pos" % i, _vec(va.position), vb.position)
            c.seq_close("pymeshio: v[%d].uv" % i, _vec(va.uv), vb.uv, 1e-6)
    return c


def run(path):
    print("\n" + "=" * 78)
    print("往返测试:", path)
    if not os.path.isfile(path):
        print("  文件不存在，跳过")
        return 1
    model = P.read_pmx(path)
    print("  读入:", model)
    print("  追加UV层数:", model.additional_uv_count,
          "蒙皮类型:", sorted({v.deform.kind for v in model.vertices}))

    tmp = os.path.join(tempfile.gettempdir(), "_roundtrip_out.pmx")
    size = P.write_pmx(tmp, model)
    print("  写出 %d 字节 -> %s" % (size, tmp))
    back = P.read_pmx(tmp)
    print("  回读:", back)

    c = compare(model, back)
    print("  字段比对: %d 项检查, %d 处不一致" % (c.checks, len(c.failures)))
    for msg in c.failures[:25]:
        print("    -", msg)
    if len(c.failures) > 25:
        print("    ... 其余 %d 处省略" % (len(c.failures) - 25))

    print("  --- pymeshio 交叉验证（剥离追加UV后）---")
    ext = crosscheck_with_pymeshio(path, model)
    if ext is True:
        pass
    elif ext is None:
        pass
    else:
        print("    pymeshio 交叉验证: %d 项检查, %d 处不一致"
              % (ext.checks, len(ext.failures)))
        for msg in ext.failures[:25]:
            print("    x", msg)

    failed = bool(c.failures) or ext is False or (ext not in (None, True) and ext.failures)
    print("  结论:", "失败" if failed else "通过")
    return 1 if failed else 0


def main():
    args = sys.argv[1:]
    paths = args if args else default_candidates()
    if not paths:
        print("找不到可用的测试模型。传一个 .pmx 路径，或用环境变量 VRM2PMX_REF_PMX 指定")
        return 2
    codes = [run(p) for p in paths]
    print("\n" + "=" * 78)
    print("总计: %d 个模型, %d 个失败" % (len(codes), sum(codes)))
    return 0 if sum(codes) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
