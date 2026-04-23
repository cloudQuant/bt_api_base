from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
src_root = project_root / "src"
if src_root.is_dir():
    sys.path.insert(0, str(src_root))
