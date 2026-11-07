"""Markdown → A4 PDF (Qt). 사용: python tools/md_to_pdf.py 입력.md 출력.pdf"""
import sys
from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QApplication

CSS = """
body { font-family: 'Malgun Gothic'; font-size: 9.5pt; color: #1e293b; }
h1 { font-size: 17pt; color: #1c46a0; } h2 { font-size: 12.5pt; color: #1c46a0; margin-top: 12px; }
table { border-collapse: collapse; } th { background: #e8effc; } th, td { border: 1px solid #cfd8e3; padding: 4px; }
code { font-family: 'Consolas'; background: #f1f5f9; }
"""


def main(src, dst):
    app = QApplication.instance() or QApplication(sys.argv)
    doc = QTextDocument()
    f = QFont()
    f.setFamilies(["Malgun Gothic", "맑은 고딕"])
    f.setPointSizeF(9.5)
    doc.setDefaultFont(f)
    doc.setDefaultStyleSheet(CSS)
    doc.setMarkdown(open(src, encoding="utf-8").read())
    w = QPdfWriter(dst)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    w.setPageMargins(QMarginsF(16, 14, 16, 14), QPageLayout.Unit.Millimeter)
    w.setResolution(300)
    doc.print_(w)
    print("done")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
