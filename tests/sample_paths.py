# -*- coding: utf-8 -*-
"""测试素材的位置解析。

测试需要两类外部素材，它们都**不随本仓库分发**，需要自备：

  * 参考 PMX —— 任意结构完整的 MMD 模型，用于读写往返与 pymeshio 交叉验证
  * 真实 VRM —— 任意 VRM 0.x / 1.0 模型，用于端到端转换校验

指定方式（优先级从高到低）：

  1. 环境变量直接给文件
       set VRM2PMX_REF_PMX=D:\\models\\某模型.pmx
       set VRM2PMX_REAL_VRM=D:\\models\\某角色.vrm
  2. 环境变量给目录，在该目录下自动查找
       set VRM2PMX_SAMPLES=D:\\models
  3. 都不设时自动搜索：仓库内 samples\\ 目录、用户下载目录（~/Downloads）

自动查找取体积最大的候选文件（截断/不完整的样本通常更小，会被排在后面）。
找不到就返回 None，调用方跳过对应测试，而不是报错。
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: 小于这个体积的文件不当作可用素材（多半是没下完或被截断）
MIN_BYTES = 64 * 1024

#: 每个搜索目录向下最多找几层
MAX_DEPTH = 2


def search_dirs(extra=""):
    """返回参与搜索的目录列表，extra 里的目录（用 os.pathsep 分隔）排在最前。"""
    dirs = []
    for part in (extra or "").split(os.pathsep):
        part = part.strip()
        if part:
            dirs.append(part)
    dirs.append(os.path.join(ROOT, "samples"))
    dirs.append(os.path.join(os.path.expanduser("~"), "Downloads"))
    return dirs


def candidates(ext, extra="", min_bytes=MIN_BYTES, max_depth=MAX_DEPTH):
    """在搜索目录里找出所有 ext 结尾且不小于 min_bytes 的文件，按体积从大到小返回。"""
    found = []
    for base in search_dirs(extra):
        if not os.path.isdir(base):
            continue
        base_abs = os.path.abspath(base)
        base_depth = base_abs.count(os.sep)
        for current, subdirs, files in os.walk(base_abs):
            if current.count(os.sep) - base_depth >= max_depth:
                subdirs[:] = []
                continue
            for name in files:
                if not name.lower().endswith(ext):
                    continue
                path = os.path.join(current, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if size >= min_bytes:
                    found.append((size, path))
    found.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in found]


def _resolve(env_name, ext):
    explicit = os.environ.get(env_name, "").strip()
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        hits = candidates(ext, extra=explicit)
        if hits:
            return hits[0]
    hits = candidates(ext, extra=os.environ.get("VRM2PMX_SAMPLES", ""))
    return hits[0] if hits else None


def find_ref_pmx():
    """参考 PMX；环境变量 VRM2PMX_REF_PMX 优先。"""
    return _resolve("VRM2PMX_REF_PMX", ".pmx")


def find_real_vrm():
    """真实 VRM；环境变量 VRM2PMX_REAL_VRM 优先。"""
    return _resolve("VRM2PMX_REAL_VRM", ".vrm")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                   # noqa: BLE001
        pass
    print("搜索目录：")
    for d in search_dirs(os.environ.get("VRM2PMX_SAMPLES", "")):
        print("  %s  %s" % (d, "(存在)" if os.path.isdir(d) else "(无)"))
    print("\n参考 PMX 候选：")
    for p in candidates(".pmx", extra=os.environ.get("VRM2PMX_SAMPLES", "")):
        print("  %10d  %s" % (os.path.getsize(p), p))
    print("\n真实 VRM 候选：")
    for p in candidates(".vrm", extra=os.environ.get("VRM2PMX_SAMPLES", "")):
        print("  %10d  %s" % (os.path.getsize(p), p))
