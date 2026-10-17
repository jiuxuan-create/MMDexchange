# -*- coding: utf-8 -*-
"""GUI 功能冒烟测试：真的建窗口、真的点转换（走线程）、真的验产物。

不依赖人工点击；弹窗被替换成记录器，避免测试卡住。
"""

import os
import sys
import time
import tkinter as tk
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vrm2pmx.gui import ConverterApp          # noqa: E402
from sample_paths import find_real_vrm         # noqa: E402

FAIL = []
NCHECK = [0]
POPUPS = []


def check(ok, label, detail=""):
    NCHECK[0] += 1
    print("  [%s] %s%s" % ("OK  " if ok else "FAIL", label,
                           ("  -> " + str(detail)) if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


def patch_messageboxes():
    def make(kind):
        def fn(title="", message="", **kw):
            POPUPS.append((kind, title, message))
            return "ok"
        return fn
    messagebox.showinfo = make("info")
    messagebox.showwarning = make("warning")
    messagebox.showerror = make("error")
    messagebox.askyesno = make("ask")


def pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def wait_idle(root, app, timeout=180.0):
    end = time.time() + timeout
    while app.busy and time.time() < end:
        root.update()
        time.sleep(0.05)
    return not app.busy


def main():
    patch_messageboxes()
    out_dir = os.path.join(ROOT, "gui_test_out")
    synth = os.path.join(ROOT, "samples", "测试模型.vrm")
    real = find_real_vrm()
    inputs = [p for p in (synth, real) if p and os.path.exists(p)]

    root = tk.Tk()
    root.withdraw()                     # 不真的弹到屏幕上，但控件树照建
    app = ConverterApp(root)

    print("=" * 70)
    print("A 控件树构建")
    print("=" * 70)
    check(app.file_list is not None, "文件列表已建立")
    check(app.log is not None, "日志区已建立")
    check(app.progress is not None, "进度条已建立")
    check(app.go_btn is not None, "转换按钮已建立")

    print()
    print("=" * 70)
    print("B 选项收集")
    print("=" * 70)
    app.out_var.set(out_dir)
    app.scale_var.set("12.5")
    app.pmxver_var.set("2.0")
    app.enc_var.set("UTF-16LE（MMD 惯用）")
    opts = app.collect_options()
    check(abs(opts.unit_scale - 12.5) < 1e-9, "单位缩放 = 12.5", opts.unit_scale)
    check(abs(opts.pmx_version - 2.0) < 1e-9, "PMX 版本 = 2.0")
    check(opts.text_encoding == 0, "文本编码 = UTF-16LE")
    check(opts.physics and opts.morphs and opts.edge, "物理/表情/描边默认开启")

    app.scale_var.set("abc")
    try:
        app.collect_options()
        check(False, "非法缩放应报参数问题")
    except ValueError as exc:
        check(True, "非法缩放被拦下", str(exc))
    app.scale_var.set("12.5")

    print()
    print("=" * 70)
    print("C 无输入时应拒绝转换")
    print("=" * 70)
    app.start_convert()
    check(len(POPUPS) == 1 and POPUPS[0][0] == "warning",
          "空列表转换给出警告弹窗", POPUPS[-1][1] if POPUPS else "无弹窗")
    check(not app.busy, "空列表不会进入忙碌状态")

    print()
    print("=" * 70)
    print("D 体检（加文件即解析）")
    print("=" * 70)
    for p in inputs:
        app.add_file(p)
    check(len(app.file_list.get(0, "end")) == len(inputs),
          "文件已进入列表", len(inputs))
    app.add_file(inputs[0])
    check(len(app.file_list.get(0, "end")) == len(inputs), "重复添加不会重复入列")

    print()
    print("=" * 70)
    print("E 真的执行一次转换（走 GUI 线程）")
    print("=" * 70)
    POPUPS.clear()
    app.start_convert()
    check(app.busy, "已进入忙碌状态")
    check(app.go_btn.instate(["disabled"]), "转换期间按钮被禁用")
    ok = wait_idle(root, app, timeout=240.0)
    check(ok, "转换在超时前结束")
    check(not app.busy, "结束后退出忙碌状态")
    check(app.go_btn.instate(["!disabled"]), "结束后按钮恢复可用")

    log_text = app.log.get("1.0", "end")
    written = []
    for line in log_text.splitlines():
        line = line.strip()
        if line.startswith("写入："):
            written.append(line[len("写入："):].strip())
    check(len(written) == len(inputs), "日志里报告了每个产出路径", len(written))
    for path in written:
        check(os.path.exists(path), "产出真实存在", os.path.basename(path))
    for p in inputs:
        check(os.path.basename(p) in log_text,
              "日志里出现源文件：%s" % os.path.basename(p))
    check(log_text.count("√") == len(inputs),
          "每个文件都打了成功标记", log_text.count("√"))
    check("转换失败" not in log_text, "没有失败记录")
    check(not [p for p in POPUPS if p[0] == "error"], "没有错误弹窗", POPUPS)
    check(app.progress["value"] == len(inputs),
          "进度条走满", app.progress["value"])
    check(app.last_out_dir == out_dir, "记住了输出目录", app.last_out_dir)

    print()
    print("   生成的 PMX：")
    for path in written:
        size = os.path.getsize(path) if os.path.exists(path) else 0
        print("     %9s 字节  %s" % ("{:,}".format(size), path))

    root.destroy()

    print()
    print("=" * 70)
    print("结果：%d 项检查，%d 项失败" % (NCHECK[0], len(FAIL)))
    for f in FAIL:
        print("  FAIL: %s" % f)
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
