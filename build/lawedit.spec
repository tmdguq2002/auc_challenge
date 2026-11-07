# PyInstaller 빌드 설정 — Windows에서: venv\Scripts\pyinstaller build\lawedit.spec
import os
from PyInstaller.utils.hooks import collect_data_files
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
block_cipher = None
EXCLUDES = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.Qt3DCore",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
            "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtNetworkAuth", "PySide6.QtSql",
            "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtQuick3D", "PySide6.QtSensors", "PySide6.QtSerialPort",
            "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSpatialAudio",
            "PySide6.QtTextToSpeech", "PySide6.QtVirtualKeyboard", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
            "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvg", "PySide6.QtHelp", "PySide6.QtUiTools",
            "tkinter", "unittest", "pytest", "lxml", "numpy", "pymupdf", "fitz", "qtawesome"]
a = Analysis([os.path.join(ROOT, "run_lawedit.py")], pathex=[ROOT], binaries=[], datas=[(os.path.join(ROOT, "lawedit", "resources"), "lawedit/resources")],
             hiddenimports=["win32com.client", "olefile", "pypdf", "anthropic"], hookspath=[], runtime_hooks=[],
             excludes=EXCLUDES, cipher=block_cipher, noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
# 폴더형(onedir): 실행할 때마다 압축을 풀지 않아 시작이 빠르다
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="법령안편집기", debug=False, strip=False, upx=False,
          console=False, icon=os.path.join(SPECPATH, "lawedit.ico"))
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="법령안편집기")
