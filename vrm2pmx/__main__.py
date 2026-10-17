# -*- coding: utf-8 -*-
"""允许 `python -m vrm2pmx ...` 直接用命令行。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
