"""실행 진입점: python -m lawedit [파일]"""
import sys


def _splash(app):
    """무거운 모듈을 읽기 전에 바로 띄우는 시작 화면."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
    from PySide6.QtWidgets import QSplashScreen
    pm = QPixmap(420, 220)
    pm.fill(QColor("#2459c7"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor("white"))
    f = QFont()
    f.setFamilies(["Malgun Gothic", "맑은 고딕"])
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect().adjusted(0, -20, 0, -20), Qt.AlignmentFlag.AlignCenter, "법령안편집기")
    f.setPixelSize(13)
    f.setBold(False)
    p.setFont(f)
    p.setPen(QColor("#dbe6ff"))
    p.drawText(pm.rect().adjusted(0, 50, 0, 50), Qt.AlignmentFlag.AlignCenter, "불러오는 중…")
    p.end()
    s = QSplashScreen(pm)
    s.show()
    app.processEvents()
    return s


def _selftest():
    """--ai-selftest: 설정된 AI 모델 연결을 시험하고 결과를 파일·종료코드로 남긴다(화면 없이)."""
    from pathlib import Path
    from lawedit.core import lawapi
    from lawedit.ai.llm import LLMConfig
    from lawedit.ai import agent
    out = lawapi.settings_dir() / "ai_selftest.txt"
    lines, code = [], 0
    try:
        lines.append("AI  OK " + agent.ping(LLMConfig.load()))
    except Exception as e:      # noqa: BLE001
        lines.append(f"AI  FAIL {e}")
        code = 1
    try:
        api = lawapi.LawAPI()
        h = api.find_law("지방공기업법")
        n = len(api.fetch_doc(h).articles()) if h else 0
        lines.append(f"LAW OK 지방공기업법 조문 {n}개" if n else "LAW FAIL 검색 결과 없음")
        code = code or (0 if n else 1)
    except Exception as e:      # noqa: BLE001
        lines.append(f"LAW FAIL {e}")
        code = 1
    Path(out).write_text("\n".join(lines), encoding="utf-8")
    sys.exit(code)


def _pdf_selftest(path: str):
    """--pdf-selftest <규정집.pdf>: 규정집 분석 결과를 파일로 남긴다(화면 없이)."""
    from pathlib import Path
    from lawedit.core import lawapi
    from lawedit.regs.regbook import build_regbook
    import time
    t = time.time()
    rb = build_regbook(path)
    arts = sum(len(e.doc.articles()) for e in rb.entries)
    msg = f"PDF OK 규정 {len(rb.entries)}개, 조문 {arts}개, {time.time() - t:.1f}초"
    Path(lawapi.settings_dir() / "pdf_selftest.txt").write_text(msg, encoding="utf-8")
    sys.exit(0)


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    if "--ai-selftest" in sys.argv:
        _selftest()
    if "--pdf-selftest" in sys.argv:
        _pdf_selftest(sys.argv[sys.argv.index("--pdf-selftest") + 1])
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("LawEdit")
    app.setOrganizationName("LawEdit")
    _install_korean(app)
    splash = _splash(app)
    from lawedit.ui import theme
    theme.apply(app)
    from lawedit.ui.main_window import MainWindow
    from lawedit.ui.widgets import text_icon
    app.setWindowIcon(text_icon("법", theme.C["primary"]))
    w = MainWindow()
    w.show()
    splash.finish(w)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        w.open_file(args[0])
    sys.exit(app.exec())


def _install_korean(app):
    """확인·취소 등 Qt 기본 단추와 대화상자 문구를 한국어로."""
    from PySide6.QtCore import QTranslator, QLibraryInfo, QLocale
    QLocale.setDefault(QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea))
    import os
    import PySide6
    paths = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
             os.path.join(os.path.dirname(PySide6.__file__), "translations")]    # 실행 파일(PyInstaller) 안
    for name in ("qtbase_ko",):
        tr = QTranslator(app)
        if any(tr.load(name, p) for p in paths):
            app.installTranslator(tr)


if __name__ == "__main__":
    main()
