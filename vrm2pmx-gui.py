# -*- coding: utf-8 -*-
"""VRM → PMX 转换器 · 图形界面入口（文件名用 ASCII，避免 .bat 里的中文被 cmd 解析坏掉）。

双击 `启动界面.bat` 会自动挑一个带完整 Tcl/Tk 的 Python 来跑本文件。
也可以直接双击本文件，或把 .vrm 拖到本文件上。

命令行转换请用：
    python -m vrm2pmx 模型.vrm -o 输出目录
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vrm2pmx.gui import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
