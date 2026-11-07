import sys
from pathlib import Path

# 저장소 최상위에서 `pytest` 로 바로 돌 수 있게
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
