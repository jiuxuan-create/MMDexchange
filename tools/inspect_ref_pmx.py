# -*- coding: utf-8 -*-
"""参考 PMX 结构探查（开发用）。

读取一个真实 PMX 文件，输出：
  1) 头部字节（magic / version / flags / 索引宽度）
  2) 坐标手性、模型朝向、单位尺度（由 つま先/足首、左右目、頭 位置推算）
  3) 骨骼命名、材质、表情、刚体、关节的字段结构与约定

用途：为 VRM -> PMX 的写出约定提供真实依据。
依赖：pymeshio（仅开发期校验用，不是交付产物的运行依赖）
"""
import struct
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

from pymeshio.pmx import reader  # noqa: E402


def dump_header(path):
    with open(path, "rb") as f:
        head = f.read(64)
    print("=== 头部字节 ===")
    print("magic      :", head[:4])
    print("version    :", struct.unpack("<f", head[4:8])[0])
    flags = head[8]
    print("flags byte :", flags, format(flags, "08b"))
    print("   bit0(UTF8) :", bool(flags & 0x01))
    print("   bit1 addUV1:", bool(flags & 0x02))
    print("   bit2 addUV2:", bool(flags & 0x04))
    print("   bit3 addUV3:", bool(flags & 0x08))
    print("   bit4 addUV4:", bool(flags & 0x10))
    print("   bit5 vcol  :", bool(flags & 0x20))
    print("enc byte   :", head[9])
    print("adduv byte :", head[10])
    print("index sizes (v,t,m,b,mo,rb):", list(head[11:17]))


def dump_overview(m):
    print("\n=== 概要 ===")
    print("name          :", m.name)
    print("english_name  :", m.english_name)
    print("comment       :", (m.comment or "").replace("\n", " ")[:160])
    print("version attr  :", m.version)
    print("vertices      :", len(m.vertices))
    print("indices       :", len(m.indices), "=> triangles", len(m.indices) // 3)
    print("textures      :", len(m.textures))
    print("materials     :", len(m.materials))
    print("bones         :", len(m.bones))
    print("morphs        :", len(m.morphs))
    print("display_slots :", len(m.display_slots))
    print("rigidbodies   :", len(m.rigidbodies))
    print("joints        :", len(m.joints))
    print("\nVertex fields  :", sorted(vars(m.vertices[0]).keys()) if m.vertices else "-")
    print("Material fields:", sorted(vars(m.materials[0]).keys()) if m.materials else "-")
    print("Bone fields    :", sorted(vars(m.bones[0]).keys()) if m.bones else "-")
    print("Morph fields   :", sorted(vars(m.morphs[0]).keys()) if m.morphs else "-")
    print("Deform type    :", type(m.vertices[0].deform).__name__ if m.vertices else "-")
    if m.rigidbodies:
        print("RigidBody field:", sorted(vars(m.rigidbodies[0]).keys()))
        print("RB param field :", sorted(vars(m.rigidbodies[0].param).keys()))
    if m.joints:
        print("Joint fields   :", sorted(vars(m.joints[0]).keys()))
    print("Display fields :", sorted(vars(m.display_slots[0]).keys()) if m.display_slots else "-")


def analyze_axes(m):
    print("\n=== 坐标手性 / 朝向 / 尺度 ===")
    byname = {b.name: b for b in m.bones}
    for n in ("頭", "首", "上半身", "センター", "左足首", "左つま先", "左目", "右目",
              "左足", "左ひざ", "下半身", "左腕", "左ひじ", "左手首"):
        b = byname.get(n)
        if b:
            p = b.position
            print(f"  {n:<8} ({p.x:9.4f}, {p.y:9.4f}, {p.z:9.4f})  parent={b.parent_index}")

    toe, ankle = byname.get("左つま先"), byname.get("左足首")
    if toe and ankle:
        d = toe.position.z - ankle.position.z
        print(f"\n  つま先.z - 足首.z = {d:+.4f}  -> 模型朝向 "
              f"{'+Z（面向 +Z）' if d > 0 else '-Z（面向 -Z）'}")
    leye, reye = byname.get("左目"), byname.get("右目")
    if leye and reye:
        print(f"  左目.x - 右目.x = {leye.position.x - reye.position.x:+.4f}  -> "
              f"{'左=+X（左手系）' if leye.position.x > reye.position.x else '左=-X（右手系）'}")
    head = byname.get("頭")
    if head:
        h = head.position.y
        print(f"  頭.y = {h:.4f} units  -> 若身高约 1.55m，则 1 unit ≈ {1.55 / h * 100:.2f} cm")
    # 目印: 目玉骨骼?
    print("\n  含'目'的骨骼:", [b.name for b in m.bones if "目" in b.name][:20])
    print("  含'足'的骨骼:", [b.name for b in m.bones if "足" in b.name][:30])


def dump_bones(m):
    print(f"\n=== 骨骼（{len(m.bones)}）===")
    for i, b in enumerate(m.bones):
        p = b.position
        extra = []
        if getattr(b, "getIkFlag", lambda: False)():
            extra.append("IK")
        if getattr(b, "getExternalRotationFlag", lambda: False)():
            extra.append(f"付与({b.effect_index},{b.effect_factor})")
        if getattr(b, "getLocalCoordinateFlag", lambda: False)():
            extra.append("軸固定")
        print(f" [{i:>3}] {b.name:<16} en={b.english_name:<16} parent={b.parent_index:>4} "
              f"pos=({p.x:8.3f},{p.y:8.3f},{p.z:8.3f}) layer={b.layer} flag=0x{b.flag:04x} "
              f"{' '.join(extra)}")


def dump_materials(m):
    print(f"\n=== 材质（{len(m.materials)}）===")
    for i, mat in enumerate(m.materials):
        print(f" [{i:>2}] {mat.name:<24} tex={mat.texture_index:>3} sph={mat.sphere_texture_index:>3}"
              f"/{mat.sphere_mode} toon={mat.toon_texture_index}/{mat.toon_sharing_flag} "
              f"flag=0x{mat.flag:02x} vtx={mat.vertex_count} "
              f"dif=({mat.diffuse_color[0]:.3f},{mat.diffuse_color[1]:.3f},{mat.diffuse_color[2]:.3f},"
              f"{mat.alpha:.3f}) edge={mat.edge_size:.2f}")
    print("\n  纹理列表:")
    for i, t in enumerate(m.textures):
        print(f"   [{i:>2}] {t}")


def dump_morphs(m):
    print(f"\n=== 表情（{len(m.morphs)}）===")
    panels = Counter()
    types = Counter()
    for i, mo in enumerate(m.morphs):
        panels[mo.panel] += 1
        types[mo.morph_type] += 1
        cnt = len(mo.offsets) if hasattr(mo, "offsets") else "-"
        print(f" [{i:>3}] panel={mo.panel} type={mo.morph_type} name={mo.name!r} "
              f"en={mo.english_name!r} offsets={cnt}")
    print("  panel 分布:", dict(panels), " type 分布:", dict(types))


def dump_physics(m):
    print(f"\n=== 刚体（{len(m.rigidbodies)}）===")
    shape = {0: "球", 1: "箱", 2: "胶囊"}
    mode = {0: "静", 1: "動", 2: "動+位置合わせ"}
    for i, rb in enumerate(m.rigidbodies):
        print(f" [{i:>3}] {rb.name:<22} bone={rb.bone_index:>4} grp={rb.collision_group} "
              f"nocoll=0x{rb.no_collision_group:04x} shape={shape.get(rb.shape_type, rb.shape_type)} "
              f"size=({rb.shape_size.x:.3f},{rb.shape_size.y:.3f},{rb.shape_size.z:.3f}) "
              f"pos=({rb.shape_position.x:.3f},{rb.shape_position.y:.3f},{rb.shape_position.z:.3f}) "
              f"mass={rb.param.mass:.3f} linD={rb.param.linear_damping:.3f} "
              f"angD={rb.param.angular_damping:.3f} mode={mode.get(rb.mode, rb.mode)}")
    print(f"\n=== 关节（{len(m.joints)}）===")
    for i, j in enumerate(m.joints):
        print(f" [{i:>3}] {j.name:<22} type={j.joint_type} a={j.rigidbody_index_a} b={j.rigidbody_index_b} "
              f"pos=({j.position.x:.3f},{j.position.y:.3f},{j.position.z:.3f}) "
              f"spT=({j.spring_constant_translation.x:.3f},{j.spring_constant_translation.y:.3f},"
              f"{j.spring_constant_translation.z:.3f})")


def dump_display(m):
    print(f"\n=== 表示枠（{len(m.display_slots)}）===")
    for i, s in enumerate(m.display_slots):
        print(f" [{i}] name={s.name!r} en={s.english_name!r} special={s.special_flag} "
              f"refs={len(s.references)} -> {s.references[:8]}{' ...' if len(s.references) > 8 else ''}")


def main():
    path = sys.argv[1]
    print("文件:", path)
    dump_header(path)
    m = reader.read_from_file(path)
    dump_overview(m)
    analyze_axes(m)
    dump_bones(m)
    dump_materials(m)
    dump_morphs(m)
    dump_physics(m)
    dump_display(m)


if __name__ == "__main__":
    main()
