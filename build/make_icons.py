"""빌드 때 한 번: 리본·탭 아이콘을 PNG로 저장 (실행 시 아이콘 글꼴 로딩을 없앤다)."""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import qtawesome as qta
from lawedit.ui import theme

src = ""
for f in ("main_window.py", "regbook_window.py", "dialogs.py", "ai_dialogs.py", "widgets.py", "theme.py"):
    src += open(os.path.join(ROOT, "lawedit", "ui", f), encoding="utf-8").read()
# 한 단어 이름(web, gavel 등)도 포함 — mdi6에 없는 문자열은 아래에서 건너뛴다
names = set(re.findall(r'"([a-z][a-z0-9]*(?:-[a-z0-9]+)*)"', src)) | {"scale-balance"}
out = os.path.join(ROOT, "lawedit", "resources", "icons")
os.makedirs(out, exist_ok=True)
n = 0
for name in sorted(names):
    for color, tag in ((theme.C["primary"], "p"), ("#ffffff", "w")):
        try:
            ic = qta.icon("mdi6." + name, color=color)
        except Exception:
            continue
        ic.pixmap(48, 48).save(os.path.join(out, f"{name}_{tag}.png"))
        n += 1
print("icons", n)
