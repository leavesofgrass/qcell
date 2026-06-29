"""Equation editor — LaTeX in, live Unicode preview, MathML out.

Renders a live Unicode approximation as you type (pure-Python), generates
presentation MathML on demand (pandoc when available, else a built-in subset
converter), and can drop the result into the active cell or the clipboard.
"""

from __future__ import annotations

from ._qtcompat import (
    QDialog,
    QFont,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)
from ..core.latexmath import to_mathml, to_unicode

try:  # QtWebEngine is an optional, binding-specific extra; load it for whichever
    # Qt binding is active. Absent → graceful fall back to the Unicode preview.
    from ._qtcompat import BINDING

    if BINDING == "PySide6":
        from PySide6.QtWebEngineWidgets import QWebEngineView
    else:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    _HAS_WEBENGINE = True
except ImportError:
    QWebEngineView = None
    _HAS_WEBENGINE = False

_MATHJAX_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script>MathJax = {{tex: {{inlineMath: [['\\\\(','\\\\)']]}}}};</script>
<script id="MathJax-script" async
  src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<style>body{{background:#1e1e2e;color:#cdd6f4;font-size:30px;margin:16px;}}</style>
</head><body>\\({latex}\\)</body></html>"""


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class EquationDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self._win = window
        self.setWindowTitle("Equation editor")
        self.resize(520, 360)
        self.setModal(False)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("LaTeX:", self))
        self._latex = QLineEdit(r"x^2 + \frac{-b}{2a}", self)
        self._latex.textChanged.connect(self._update_preview)
        layout.addWidget(self._latex)

        big = QFont()
        big.setPointSize(20)
        self._preview = QLabel("", self)
        self._preview.setFont(big)
        self._preview.setAccessibleName("Equation preview (Unicode)")
        self._preview.setStyleSheet("padding:12px;")
        layout.addWidget(self._preview)

        self._web = None
        if _HAS_WEBENGINE:
            self._web = QWebEngineView(self)
            self._web.setMinimumHeight(120)
            self._web.setAccessibleName("Equation preview (MathJax)")
            layout.addWidget(self._web)

        self._mathml = QPlainTextEdit(self)
        self._mathml.setReadOnly(True)
        self._mathml.setMaximumHeight(120)
        layout.addWidget(self._mathml)

        row = QHBoxLayout()
        for label, slot in [
            ("Generate MathML", self._gen_mathml),
            ("Insert into cell", self._insert),
            ("Copy MathML", self._copy_mathml),
            ("Get pandoc", self._get_pandoc),
        ]:
            b = QPushButton(label, self)
            b.clicked.connect(slot)
            row.addWidget(b)
        layout.addLayout(row)
        self._status = QLabel("", self)
        layout.addWidget(self._status)
        self._update_preview()

    def _update_preview(self) -> None:
        latex = self._latex.text()
        try:
            self._preview.setText(to_unicode(latex))
        except Exception as exc:  # pragma: no cover - defensive
            self._preview.setText(f"(preview error: {exc})")
        if self._web is not None:
            self._web.setHtml(_MATHJAX_HTML.format(latex=_html_escape(latex)))

    def _gen_mathml(self) -> None:
        from ..core import pandoc

        self._mathml.setPlainText(to_mathml(self._latex.text()))
        self._status.setText("pandoc MathML" if pandoc.available() else "built-in MathML (no pandoc)")

    def _insert(self) -> None:
        t = self._win._table
        row, col = max(0, t.currentRow()), max(0, t.currentColumn())
        self._win._doc.workbook.sheet.set_cell(row, col, to_unicode(self._latex.text()))
        self._win._doc.mark_dirty()
        self._win.refresh_table()
        self._status.setText("inserted Unicode equation into cell")

    def _copy_mathml(self) -> None:
        from ._qtcompat import QApplication

        if not self._mathml.toPlainText():
            self._gen_mathml()
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self._mathml.toPlainText())
        self._status.setText("MathML copied to clipboard")

    def _get_pandoc(self) -> None:
        from ..core import pandoc

        if pandoc.available():
            self._status.setText("pandoc already available")
            return
        self._status.setText("installing pandoc…")
        ok = pandoc.ensure()
        self._status.setText("pandoc installed" if ok else "pandoc install failed (offline?)")
