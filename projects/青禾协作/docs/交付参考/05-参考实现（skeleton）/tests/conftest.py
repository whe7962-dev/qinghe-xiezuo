import sys
from pathlib import Path

# 让 pytest 从任意目录运行都能 import app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
