# -*- coding: utf-8 -*-
"""vrm2pmx 的 Tkinter 图形界面（只用标准库，不需要额外安装任何东西）。

启动：
    python VRM转PMX.py
或直接把 .vrm 文件拖到 VRM转PMX.py 上。
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import read_vrm_info, __version__
from .convert import ConversionOptions, convert
from .transform import DEFAULT_UNIT_SCALE

APP_TITLE = "VRM → PMX 转换器  v%s" % __version__
FILE_TYPES = [("VRM / glTF 模型", "*.vrm *.glb *.gltf"),
              ("VRM 文件", "*.vrm"),
              ("glTF 二进制", "*.glb"),
              ("glTF 文本", "*.gltf"),
              ("全部文件", "*.*")]
ENCODING_CHOICES = [("UTF-16LE（MMD 惯用）", 0), ("UTF-8", 1)]
VERSION_CHOICES = ["2.0", "2.1"]


def enable_dpi_awareness():
    """Windows 高分屏下避免界面发虚。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class ConverterApp(object):
    def __init__(self, root, initial_files=None):
        self.root = root
        self.queue = queue.Queue()
        self.busy = False
        self.last_out_dir = None

        root.title(APP_TITLE)
        root.geometry("980x820")
        root.minsize(860, 660)

        self._build_style()
        self._build_widgets()

        if initial_files:
            for path in initial_files:
                self.add_file(path, quiet=True)
            self.refresh_inputs()

        self.root.after(120, self._drain_queue)

    # ------------------------------------------------------------ 界面搭建
    def _build_style(self):
        style = ttk.Style()
        for theme in ("vista", "winnative", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("Hint.TLabel", foreground="#666")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Go.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_widgets(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        # ---- 1. 输入文件
        box_in = ttk.LabelFrame(outer, text=" 1. 选择要转换的模型 ", padding=8)
        box_in.grid(row=0, column=0, sticky="ew")
        box_in.columnconfigure(0, weight=1)

        list_wrap = ttk.Frame(box_in)
        list_wrap.grid(row=0, column=0, sticky="nsew")
        list_wrap.columnconfigure(0, weight=1)
        self.file_list = tk.Listbox(list_wrap, height=4, selectmode="extended",
                                    activestyle="none")
        self.file_list.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_wrap, orient="vertical",
                           command=self.file_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.file_list.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(box_in)
        btns.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ttk.Button(btns, text="添加文件…", width=12,
                   command=self.choose_files).pack(pady=(0, 4))
        ttk.Button(btns, text="移除所选", width=12,
                   command=self.remove_selected).pack(pady=4)
        ttk.Button(btns, text="清空", width=12,
                   command=self.clear_files).pack(pady=4)

        # ---- 2. 输出目录
        box_out = ttk.LabelFrame(outer, text=" 2. 输出位置 ", padding=8)
        box_out.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        box_out.columnconfigure(1, weight=1)
        self.out_var = tk.StringVar()
        ttk.Label(box_out, text="输出目录").grid(row=0, column=0, sticky="w")
        ttk.Entry(box_out, textvariable=self.out_var).grid(
            row=0, column=1, sticky="ew", padx=6)
        ttk.Button(box_out, text="浏览…", width=10,
                   command=self.choose_out_dir).grid(row=0, column=2)
        ttk.Label(box_out, text="留空则输出到源文件所在目录；贴图会一起写到 tex\\ 子目录。",
                  style="Hint.TLabel").grid(row=1, column=0, columnspan=3,
                                            sticky="w", pady=(4, 0))

        # ---- 3. 选项
        box_opt = ttk.LabelFrame(outer, text=" 3. 转换选项 ", padding=8)
        box_opt.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for col in range(4):
            box_opt.columnconfigure(col, weight=1, uniform="opt")

        def field(row, col, text, widget, colspan=1):
            ttk.Label(box_opt, text=text).grid(row=row, column=col,
                                               columnspan=colspan, sticky="w",
                                               padx=(0, 10))
            widget.grid(row=row + 1, column=col, columnspan=colspan,
                        sticky="ew", padx=(0, 10), pady=(2, 8))

        self.scale_var = tk.StringVar(value=str(DEFAULT_UNIT_SCALE))
        field(0, 0, "单位缩放（1 米 = 多少单位）",
              ttk.Spinbox(box_opt, from_=1.0, to=100.0, increment=0.5,
                          textvariable=self.scale_var))

        self.pmxver_var = tk.StringVar(value="2.0")
        field(0, 1, "PMX 版本",
              ttk.Combobox(box_opt, values=VERSION_CHOICES, state="readonly",
                           textvariable=self.pmxver_var))

        self.enc_var = tk.StringVar(value=ENCODING_CHOICES[0][0])
        field(0, 2, "文本编码",
              ttk.Combobox(box_opt, values=[c[0] for c in ENCODING_CHOICES],
                           state="readonly", textvariable=self.enc_var))

        self.edge_size_var = tk.StringVar(value="1.0")
        field(0, 3, "描边宽度",
              ttk.Spinbox(box_opt, from_=0.0, to=10.0, increment=0.1,
                          textvariable=self.edge_size_var))

        self.name_var = tk.StringVar()
        field(2, 0, "模型名（留空则用 VRM 文件里自带的名字）",
              ttk.Entry(box_opt, textvariable=self.name_var), colspan=4)

        self.edge_var = tk.BooleanVar(value=True)
        self.ground_var = tk.BooleanVar(value=False)
        self.physics_var = tk.BooleanVar(value=True)
        self.auto_physics_var = tk.BooleanVar(value=True)
        self.morphs_var = tk.BooleanVar(value=True)
        self.extra_bones_var = tk.BooleanVar(value=True)
        self.flipv_var = tk.BooleanVar(value=False)

        opts = [("生成描边（轮廓线）", self.edge_var),
                ("脚底对齐到 y=0", self.ground_var),
                ("生成物理（刚体/关节）", self.physics_var),
                ("自动补物理链", self.auto_physics_var),
                ("生成表情", self.morphs_var),
                ("保留额外骨骼", self.extra_bones_var),
                ("垂直翻转 UV（贴图上下颠倒时用）", self.flipv_var)]
        for i, (text, var) in enumerate(opts):
            ttk.Checkbutton(box_opt, text=text, variable=var).grid(
                row=4 + i // 2, column=(i % 2) * 2, columnspan=2,
                sticky="w", pady=1)

        # ---- 4. 操作与日志
        box_run = ttk.LabelFrame(outer, text=" 4. 转换 ", padding=8)
        box_run.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        box_run.columnconfigure(0, weight=1)
        box_run.rowconfigure(2, weight=1)

        bar = ttk.Frame(box_run)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        self.go_btn = ttk.Button(bar, text="开始转换", style="Go.TButton",
                                 width=14, command=self.start_convert)
        self.go_btn.grid(row=0, column=0)
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(bar, text="打开输出目录", width=14,
                   command=self.open_out_dir).grid(row=0, column=2)
        ttk.Button(bar, text="清空日志", width=10,
                   command=self.clear_log).grid(row=0, column=3, padx=(6, 0))

        self.status_var = tk.StringVar(value="待转换")
        ttk.Label(box_run, textvariable=self.status_var,
                  style="Hint.TLabel").grid(row=1, column=0, sticky="w",
                                            pady=(4, 4))

        log_wrap = ttk.Frame(box_run)
        log_wrap.grid(row=2, column=0, sticky="nsew")
        log_wrap.columnconfigure(0, weight=1)
        log_wrap.rowconfigure(0, weight=1)
        self.log = tk.Text(log_wrap, height=10, wrap="word", state="disabled",
                           background="#fbfbfb", relief="solid", borderwidth=1)
        self.log.grid(row=0, column=0, sticky="nsew")
        lsb = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview)
        lsb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=lsb.set)
        self.log.tag_configure("err", foreground="#b00020")
        self.log.tag_configure("ok", foreground="#0a7d28")
        self.log.tag_configure("warn", foreground="#a06000")
        self.log.tag_configure("head", foreground="#1a3f8f",
                               font=("Consolas", 9, "bold"))

    # ------------------------------------------------------------ 文件操作
    def choose_files(self):
        paths = filedialog.askopenfilenames(title="选择 VRM / glTF 模型",
                                            filetypes=FILE_TYPES)
        if not paths:
            return
        for p in paths:
            self.add_file(p)
        self.refresh_inputs()

    def add_file(self, path, quiet=False):
        path = os.path.abspath(path)
        existing = list(self.file_list.get(0, "end"))
        if path in existing:
            if not quiet:
                self.log_line("已在列表中：%s" % path, "warn")
            return
        self.file_list.insert("end", path)
        if not quiet:
            self.inspect(path)

    def remove_selected(self):
        for idx in reversed(self.file_list.curselection()):
            self.file_list.delete(idx)

    def clear_files(self):
        self.file_list.delete(0, "end")

    def refresh_inputs(self):
        pass

    def choose_out_dir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.out_var.set(d)

    def open_out_dir(self):
        target = self.last_out_dir or self.out_var.get().strip()
        if not target or not os.path.isdir(target):
            messagebox.showinfo("提示", "还没有可打开的输出目录。")
            return
        try:
            if sys.platform == "win32":
                os.startfile(target)          # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception as exc:               # noqa: BLE001
            messagebox.showwarning("打不开", str(exc))

    # ------------------------------------------------------------ 日志
    def log_line(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def inspect(self, path):
        try:
            info = read_vrm_info(path)
        except Exception as exc:               # noqa: BLE001
            self.log_line("× 解析失败 %s" % os.path.basename(path), "err")
            self.log_line("   %s" % exc, "err")
            return
        self.log_line("● %s" % os.path.basename(path), "head")
        self.log_line("   VRM %s ｜ %s" % (
            "1.0" if info["version"] == 1 else "0.x",
            info["name"] or "(未命名)"))
        self.log_line("   顶点 %s / 三角 %s / 材质 %s ｜ 人形骨 %d / 表情 %d / "
                      "物理链 %d / 碰撞体 %d" % (
                          "{:,}".format(info["vertices"]),
                          "{:,}".format(info["triangles"]),
                          info["materials"], info["humanoid_bones"],
                          info["expressions"], info["springs"],
                          info["colliders"]))
        if info["humanoid_bones"] < 20:
            self.log_line("   ! 人形骨偏少，转换后可能缺少标准骨骼。", "warn")
        if info["expressions"] == 0:
            self.log_line("   ! 没有表情数据，转换后表情面板会是空的。", "warn")

    # ------------------------------------------------------------ 转换
    def collect_options(self):
        try:
            scale = float(self.scale_var.get())
        except ValueError:
            raise ValueError("单位缩放必须是数字")
        if scale <= 0:
            raise ValueError("单位缩放必须大于 0")
        try:
            edge_size = float(self.edge_size_var.get() or 0.0)
        except ValueError:
            raise ValueError("描边宽度必须是数字")
        enc = dict(ENCODING_CHOICES).get(self.enc_var.get(), 0)
        return ConversionOptions(
            unit_scale=scale,
            ground_align=self.ground_var.get(),
            edge=self.edge_var.get(),
            edge_size=edge_size,
            auto_physics=self.auto_physics_var.get(),
            physics=self.physics_var.get(),
            morphs=self.morphs_var.get(),
            keep_extra_bones=self.extra_bones_var.get(),
            flip_v=self.flipv_var.get(),
            pmx_version=float(self.pmxver_var.get()),
            text_encoding=enc,
            model_name=(self.name_var.get().strip() or None),
        )

    def start_convert(self):
        if self.busy:
            return
        files = list(self.file_list.get(0, "end"))
        if not files:
            messagebox.showwarning("还没有输入", "请先添加至少一个 VRM 文件。")
            return
        try:
            options = self.collect_options()
        except ValueError as exc:
            messagebox.showerror("参数有问题", str(exc))
            return
        out_dir = self.out_var.get().strip() or None
        if out_dir:
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as exc:           # noqa: BLE001
                messagebox.showerror("输出目录不可用", str(exc))
                return

        self.busy = True
        self.go_btn.configure(state="disabled")
        self.progress.configure(value=0, maximum=len(files))
        self.status_var.set("转换中…")
        self.log_line("")
        self.log_line("═" * 52, "head")
        self.log_line("开始转换 %d 个文件" % len(files), "head")
        thread = threading.Thread(target=self._worker,
                                  args=(files, out_dir, options), daemon=True)
        thread.start()

    def _worker(self, files, out_dir, options):
        for i, path in enumerate(files):
            name = os.path.basename(path)
            try:
                result = convert(
                    path, out_dir, options,
                    progress=lambda m, n=name: self.queue.put(("log", "   · " + m)))
            except Exception as exc:           # noqa: BLE001
                import traceback
                self.queue.put(("fail", (name, str(exc), traceback.format_exc())))
            else:
                self.queue.put(("done", (name, result)))
            self.queue.put(("step", i + 1))
        self.queue.put(("finish", None))

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.log_line(payload)
                elif kind == "step":
                    self.progress.configure(value=payload)
                elif kind == "done":
                    name, result = payload
                    self.last_out_dir = os.path.dirname(result.output)
                    if not self.out_var.get().strip():
                        self.out_var.set(self.last_out_dir)
                    self.log_line("√ %s" % name, "ok")
                    self.log_line("   写入：%s" % result.output, "ok")
                    self.log_line("   %s" % result.summary())
                    self.log_line("   耗时 %.2f 秒，%.1f KB" % (
                        result.elapsed, result.stats.get("bytes", 0) / 1024.0))
                    for w in result.warnings:
                        self.log_line("   ! %s" % w, "warn")
                elif kind == "fail":
                    name, msg, tb = payload
                    self.log_line("× %s 转换失败：%s" % (name, msg), "err")
                    self.log_line(tb, "err")
                elif kind == "finish":
                    self.busy = False
                    self.go_btn.configure(state="normal")
                    self.status_var.set("完成。PMX 已就绪，可直接拖进 MMD。")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_queue)


def main(argv=None):
    enable_dpi_awareness()
    argv = list(sys.argv[1:] if argv is None else argv)
    models = [a for a in argv if os.path.isfile(a)]
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print("× 这个 Python 装了 tkinter，但缺少 Tcl/Tk 运行库，开不了窗口。")
        print("  详细原因：%s" % exc)
        print("")
        print("  请换一个带完整 Tk 的 Python 来启动界面，例如：")
        print("     py -3 VRM转PMX.py")
        print("     python3 VRM转PMX.py")
        print("  或到 python.org 装一个标准版 Python（安装时勾选 tcl/tk）。")
        print("")
        print("  不想装 Python 也可以直接用命令行转换：")
        print("     python -m vrm2pmx 模型.vrm -o 输出目录")
        return 3
    app = ConverterApp(root, initial_files=models)
    app.log_line(APP_TITLE)
    app.log_line("提示：把 .vrm 文件添加进来即可。转换前请先确认模型的使用条款——")
    app.log_line("      多数模型禁止二次配布或改造，转换后的 PMX 同样受原条款约束。")
    if not models:
        app.log_line("")
        app.log_line("尚未添加文件。点「添加文件…」，或把 .vrm 拖到本程序图标上。")
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
