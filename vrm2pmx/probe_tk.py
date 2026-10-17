# -*- coding: utf-8 -*-
"""探测当前 Python 是否能真正创建一个 Tk 窗口（有些 Python 装了 tkinter 却缺 Tcl 运行库）。

能被创建则退出码 0，否则退出码 1。启动器用它挑选可用的解释器。
"""

import sys


def main():
    try:
        import tkinter
    except Exception as exc:                       # noqa: BLE001
        sys.stderr.write("tkinter 不可导入: %s\n" % exc)
        return 1
    try:
        root = tkinter.Tk()
    except Exception as exc:                       # noqa: BLE001
        sys.stderr.write("Tk 初始化失败: %s\n" % exc)
        return 1
    try:
        root.withdraw()
        root.update_idletasks()
        sys.stdout.write("Python %s\n%s\nTk %s / Tcl %s\n"
                         % (sys.version.split()[0], sys.executable,
                            root.tk.call("info", "patchlevel"),
                            tkinter.TclVersion))
    finally:
        root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
