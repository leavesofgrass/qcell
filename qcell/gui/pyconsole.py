"""Embedded Python console — scripting inside the editor, run out-of-process.

User code runs in a SEPARATE process (:mod:`qcell.console_worker`, via
:class:`~qcell.gui.console_bridge.ConsoleBridge`), so a crash or segfault there
can't take down the GUI. The live workbook is shipped to the worker and the result
shipped back each command as a JSON envelope. It is still **untrusted code running
with your privileges** (gated by the consent prompt) — the subprocess gives
crash/memory isolation, not yet a security boundary.

Worker namespace: ``doc``, ``wb``, ``sheet()``, ``cell(ref)``, ``put(ref, val)``,
``refresh()``, ``rpn``, the engineering toolkit, and the data-science libraries
when installed.
"""

from __future__ import annotations

from ._qtcompat import QDialog, QFont, QLineEdit, QPlainTextEdit, QVBoxLayout

_BANNER = (
    "qcell Python console (sandboxed — runs in a separate process).\n"
    "Namespace: doc, wb, sheet(), cell(ref), put(ref, val), refresh(), rpn; "
    "engineering: matrix, eigen, units, numeric, complexnum, fft, interp, signal, "
    "spectral, filters, ode, ode_implicit, resynth, stats, cluster, ml, trees, "
    "bayes, metrics, gmm, compile_expr, read_matrix(rng), write_matrix(cell, mat), "
    "sheet_to_df(rng), df_to_sheet(df, cell); data science (if installed): "
    "np/numpy, pd/pandas, scipy, sm/statsmodels, sklearn, pg/pingouin, pm/pymc, "
    "sksurv.\n(The first command starts the sandbox; later commands reuse it.)\n>>> "
)


class PyConsole(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self._win = window
        self.setWindowTitle("Python console (sandboxed)")
        self.resize(620, 420)
        self.setModal(False)
        from .console_bridge import ConsoleBridge

        self._bridge = ConsoleBridge()
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._out = QPlainTextEdit(self)
        self._out.setReadOnly(True)
        self._out.setFont(mono)
        self._out.setPlainText(_BANNER)
        layout.addWidget(self._out)
        self._in = QLineEdit(self)
        self._in.setFont(mono)
        self._in.returnPressed.connect(self._run)
        layout.addWidget(self._in)

    def _run(self) -> None:
        src = self._in.text()
        self._in.clear()
        self._out.appendPlainText(src)
        envelope = self._win._doc.workbook.to_envelope()
        resp = self._bridge.execute(src, envelope)
        out = resp.get("output", "")
        if out:
            self._out.appendPlainText(out.rstrip("\n"))
        if resp.get("crashed"):
            reason = resp.get("stderr") or ""
            self._out.appendPlainText("[console process exited — it will restart on "
                                      "the next command]" + (f"\n{reason}" if reason else ""))
        else:
            try:
                self._win._doc.workbook.load_envelope(resp["envelope"])
                self._win._doc.mark_dirty()
                self._win.refresh_table()
            except Exception as exc:  # pragma: no cover - defensive
                self._out.appendPlainText(f"[could not apply workbook changes: {exc}]")
        self._out.appendPlainText(">>> ")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._bridge.close()
        super().closeEvent(event)
