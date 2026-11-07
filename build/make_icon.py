import sys, os
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lawedit.ui.widgets import text_icon
pm = text_icon("법", "#1f4e9a").pixmap(256, 256)
pm.save(os.path.join(os.path.dirname(__file__), "lawedit.ico"))
print("icon ok")
