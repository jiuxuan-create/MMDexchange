# -*- coding: utf-8 -*-
"""vrm2pmx 命令行入口。

    python -m vrm2pmx 模型.vrm
    python -m vrm2pmx 模型1.vrm 模型2.vrm -o 输出目录
    python -m vrm2pmx *.vrm -o out --unit-scale 12.5 --no-physics
    python -m vrm2pmx --info 模型.vrm
"""

import argparse
import glob
import json
import os
import sys

from . import read_vrm_info
from . import __version__
from .convert import ConversionOptions, convert
from .transform import DEFAULT_UNIT_SCALE

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ENCODINGS = {"utf16": 0, "utf-8": 1, "utf8": 1}


def build_parser():
    p = argparse.ArgumentParser(
        prog="vrm2pmx",
        description="把 VRM（1.0 / 0.x）虚拟形象转换成 MMD 可用的 PMX 模型。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python -m vrm2pmx 角色.vrm
  python -m vrm2pmx 角色.vrm -o D:\\MMD\\model
  python -m vrm2pmx *.vrm -o out --encoding utf-8 --pmx-version 2.1
  python -m vrm2pmx --info 角色.vrm
""")
    p.add_argument("inputs", nargs="*", help="VRM/GLB 文件，支持通配符")
    p.add_argument("-o", "--out", default=None,
                   help="输出目录（默认与源文件同目录）")
    p.add_argument("--info", action="store_true",
                   help="只打印 VRM 信息，不做转换")
    p.add_argument("--unit-scale", type=float, default=DEFAULT_UNIT_SCALE,
                   help="1 米等于多少个 MMD 单位（默认 %(default)s，即 1 单位≈8cm）")
    p.add_argument("--ground-align", action="store_true",
                   help="按模型最低点对齐脚底到 y=0")
    p.add_argument("--no-edge", action="store_true", help="不生成描边（轮廓线）")
    p.add_argument("--edge-size", type=float, default=1.0,
                   help="描边宽度（默认 %(default)s）")
    p.add_argument("--no-auto-physics", action="store_true",
                   help="模型没有 SpringBone 时不按骨骼名自动补物理链")
    p.add_argument("--no-physics", action="store_true", help="完全不生成刚体/关节")
    p.add_argument("--no-morphs", action="store_true", help="完全不生成表情")
    p.add_argument("--no-extra-bones", action="store_true",
                   help="不保留 VRM 里额外挂载的骨骼（只保留人形骨与 MMD 控制骨）")
    p.add_argument("--flip-v", action="store_true",
                   help="垂直翻转 UV（贴图上下颠倒时用）")
    p.add_argument("--pmx-version", type=float, default=2.0, choices=(2.0, 2.1),
                   help="输出的 PMX 版本（默认 2.0，兼容性最好）")
    p.add_argument("--encoding", default="utf16", choices=("utf16", "utf-8"),
                   help="PMX 文本编码（默认 utf16，即 UTF-16LE）")
    p.add_argument("--name", default=None, help="覆盖输出模型名")
    p.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p.add_argument("-q", "--quiet", action="store_true", help="不打印过程日志")
    p.add_argument("-V", "--version", action="version",
                   version="vrm2pmx %s" % __version__)
    return p


def expand_inputs(patterns):
    files = []
    for pat in patterns:
        if os.path.isfile(pat):
            files.append(pat)
            continue
        hits = sorted(glob.glob(pat))
        if not hits:
            print("找不到文件：%s" % pat, file=sys.stderr)
        files.extend(h for h in hits if os.path.isfile(h))
    seen = set()
    ordered = []
    for f in files:
        key = os.path.abspath(f).lower()
        if key not in seen:
            seen.add(key)
            ordered.append(f)
    return ordered


def print_info(path):
    info = read_vrm_info(path)
    print("─" * 62)
    print("文件   : %s" % path)
    print("格式   : VRM %s（spec %s）" % (
        "1.0" if info["version"] == 1 else "0.x",
        info["spec_version"] or "-"))
    print("名称   : %s" % (info["name"] or "(未命名)"))
    if info["authors"]:
        print("作者   : %s" % "、".join(info["authors"]))
    if info["license"]:
        print("授权   : %s" % info["license"])
    print("规模   : 顶点 %s / 三角 %s / 网格 %s / 材质 %s / 贴图 %s"
          % ("{:,}".format(info["vertices"]), "{:,}".format(info["triangles"]),
             info["meshes"], info["materials"], info["textures"]))
    print("角色   : 人形骨 %d 根 / 表情 %d 个 / 物理链 %d 条 / 碰撞体 %d 个"
          % (info["humanoid_bones"], info["expressions"], info["springs"],
             info["colliders"]))
    if info["extensions"]:
        print("扩展   : %s" % ", ".join(info["extensions"]))
    print("─" * 62)
    return info


def main(argv=None):
    args = build_parser().parse_args(argv)
    files = expand_inputs(args.inputs)

    if not files:
        if not args.inputs:
            build_parser().print_help()
            return 2
        print("没有可处理的文件。", file=sys.stderr)
        return 2

    if args.info:
        for f in files:
            try:
                print_info(f)
            except Exception as exc:  # noqa: BLE001
                print("解析失败 %s：%s" % (f, exc), file=sys.stderr)
                return 1
        return 0

    options = ConversionOptions(
        unit_scale=args.unit_scale,
        ground_align=args.ground_align,
        edge=not args.no_edge,
        edge_size=args.edge_size,
        auto_physics=not args.no_auto_physics,
        physics=not args.no_physics,
        morphs=not args.no_morphs,
        keep_extra_bones=not args.no_extra_bones,
        flip_v=args.flip_v,
        pmx_version=args.pmx_version,
        text_encoding=ENCODINGS[args.encoding],
        model_name=args.name,
    )

    reports = []
    failed = 0
    for index, path in enumerate(files, 1):
        if not args.quiet:
            print("=" * 62)
            print("[%d/%d] %s" % (index, len(files), os.path.basename(path)))
            print("=" * 62)
        try:
            result = convert(
                path, args.out, options,
                progress=(None if args.quiet else lambda m: print("   · " + m)))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            reports.append({"input": path, "ok": False, "error": str(exc)})
            print("转换失败：%s" % exc, file=sys.stderr)
            if not args.json:
                import traceback
                traceback.print_exc()
            continue
        reports.append({
            "input": path,
            "ok": True,
            "output": result.output,
            "textures": result.textures,
            "warnings": result.warnings,
            "stats": result.stats,
            "elapsed": round(result.elapsed, 3),
        })
        if not args.quiet:
            print("   产出：%s" % result.output)
            print("   统计：%s" % result.summary())
            print("   耗时：%.2f 秒" % result.elapsed)
            for w in result.warnings:
                print("   ! %s" % w)

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        ok = len(files) - failed
        print("\n完成：成功 %d / 共 %d。" % (ok, len(files)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
