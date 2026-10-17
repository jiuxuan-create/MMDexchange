# -*- coding: utf-8 -*-
"""一键跑完所有测试。

    python tests/run_all.py

会在当前解释器下依次跑：
  1. PMX 读写往返 + pymeshio 交叉验证（需要参考 PMX，缺了就跳过）
  2. 合成 VRM 端到端转换 + 逐项校验
  3. 真实 VRM 端到端转换 + 逐项校验（找到样本才跑）
  4. GUI 功能冒烟（当前解释器没有可用 Tk 时跳过并提示换解释器）

任何一项失败都会体现在最后的汇总里，退出码非 0。
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sample_paths import find_real_vrm, find_ref_pmx  # noqa: E402


def run(title, args, timeout=600):
    print()
    print("#" * 76)
    print("# %s" % title)
    print("#" * 76)
    started = time.time()
    proc = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)
    text = proc.stdout.decode("utf-8", "replace")
    print(text.rstrip())
    print("- 退出码 %d，用时 %.1f 秒" % (proc.returncode, time.time() - started))
    return proc.returncode


def tk_available():
    try:
        import tkinter
        root = tkinter.Tk()
        root.destroy()
        return True, ""
    except Exception as exc:                        # noqa: BLE001
        return False, str(exc).splitlines()[0]


def main():
    py = sys.executable
    results = []

    ref_pmx = find_ref_pmx()
    if ref_pmx:
        code = run("1/4  PMX 读写往返 + pymeshio 交叉验证",
                   [py, os.path.join(HERE, "test_pmx_roundtrip.py"), ref_pmx])
        results.append(("PMX 往返/交叉验证", code))
    else:
        print("\n[跳过] 找不到参考 PMX。设置环境变量 VRM2PMX_REF_PMX 指向一个 .pmx，")
        print("       或把模型放进 samples\\ 目录（参考素材不随仓库分发）。")
        results.append(("PMX 往返/交叉验证", None))

    code = run("2/4  合成 VRM 端到端转换 + 校验",
               [py, os.path.join(HERE, "test_conversion.py")])
    results.append(("合成 VRM 转换", code))

    real = find_real_vrm()
    if real:
        code = run("3/4  真实 VRM 端到端转换 + 校验",
                   [py, os.path.join(HERE, "validate_conversion.py"), real])
        results.append(("真实 VRM 转换", code))
    else:
        print("\n[跳过] 找不到真实 VRM 样本。设置环境变量 VRM2PMX_REAL_VRM 指向一个 .vrm。")
        results.append(("真实 VRM 转换", None))

    ok, why = tk_available()
    if ok:
        code = run("4/4  GUI 功能冒烟", [py, os.path.join(HERE, "test_gui_smoke.py")])
        results.append(("GUI 冒烟", code))
    else:
        print("\n[跳过] 当前解释器没有可用的 Tk：%s" % why)
        print("       换一个带完整 Tcl/Tk 的 Python 再跑，例如：")
        print("         python3 tests\\run_all.py")
        print("       或用启动器自带的探测：")
        print("         python3 vrm2pmx\\probe_tk.py")
        results.append(("GUI 冒烟", None))

    print()
    print("=" * 76)
    print("汇总")
    print("=" * 76)
    failed = 0
    skipped = 0
    for name, code in results:
        if code is None:
            state = "跳过"
            skipped += 1
        elif code == 0:
            state = "通过"
        else:
            state = "失败（退出码 %d）" % code
            failed += 1
        print("  %-24s %s" % (name, state))
    print("=" * 76)
    print("通过 %d / 失败 %d / 跳过 %d"
          % (len(results) - failed - skipped, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
