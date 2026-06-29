"""Embedded Python console — scripting inside the editor.

A persistent REPL whose namespace is wired to the live workbook: ``doc``, ``wb``,
``sheet()`` (active), ``cell(ref)`` / ``put(ref, value)``, ``rpn`` (a calculator),
and ``refresh()``. Runs trusted Python (like macros) — not a sandbox.
"""

from __future__ import annotations

import code
import contextlib
import io

from ._qtcompat import QDialog, QFont, QLineEdit, QPlainTextEdit, QVBoxLayout


class _LazyModule:
    """A stand-in that imports its module on first attribute access.

    Lets heavy optional packages (pymc, scikit-survival) sit in the console
    namespace without paying their import cost until they're actually used.
    """

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_mod", None)

    def _load(self):
        mod = object.__getattribute__(self, "_mod")
        if mod is None:
            import importlib

            mod = importlib.import_module(object.__getattribute__(self, "_name"))
            object.__setattr__(self, "_mod", mod)
        return mod

    def __getattr__(self, attr):
        return getattr(self._load(), attr)

    def __repr__(self) -> str:
        name = object.__getattribute__(self, "_name")
        return f"<module {name!r} (qcell lazy — imports on first use)>"


class PyConsole(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self._win = window
        self.setWindowTitle("Python console")
        self.resize(620, 420)
        self.setModal(False)
        # Build the interpreter (and its heavy scientific imports) lazily on the
        # first command, so opening the console at startup stays fast.
        self._console = None
        self._build()

    def _interpreter(self):
        if self._console is None:
            self._console = code.InteractiveInterpreter(self._namespace())
        return self._console

    def _namespace(self) -> dict:
        win = self._win
        doc = win._doc

        def sheet():
            return doc.workbook.sheet

        def cell(ref):
            return doc.workbook.sheet.get(ref)

        def put(ref, value):
            doc.workbook.sheet.set(ref, value if isinstance(value, str) else str(value))

        def refresh():
            win.refresh_table()

        def read_matrix(rng):
            """Read a range like 'A1:C3' into a list-of-lists of floats."""
            from ..core.reference import parse_range

            r1, c1, r2, c2 = parse_range(rng)
            sh = doc.workbook.sheet
            return [[float(sh.get_value(r, c) or 0) for c in range(c1, c2 + 1)]
                    for r in range(r1, r2 + 1)]

        def write_matrix(top_left, mat):
            """Write a list-of-lists starting at a cell like 'E1'."""
            from ..core.reference import parse_a1

            r0, c0 = parse_a1(top_left)
            sh = doc.workbook.sheet
            for i, row in enumerate(mat):
                for j, v in enumerate(row):
                    sh.set_cell(r0 + i, c0 + j, repr(v))
            win.refresh_table()

        def sheet_to_df(rng=None, header=True):
            """Read the sheet (or an 'A1:C9' range) into a pandas DataFrame.

            With ``header=True`` the first row supplies the column names.
            """
            if _pd is None:
                raise RuntimeError("pandas is not installed")
            from ..core.reference import parse_range

            sh = doc.workbook.sheet
            if rng:
                r1, c1, r2, c2 = parse_range(rng)
            else:
                nr, nc = sh.used_bounds()
                r1, c1, r2, c2 = 0, 0, nr - 1, nc - 1
            rows = [[sh.get_value(r, c) for c in range(c1, c2 + 1)]
                    for r in range(r1, r2 + 1)]
            if header and rows:
                return _pd.DataFrame(rows[1:], columns=[str(x) for x in rows[0]])
            return _pd.DataFrame(rows)

        def df_to_sheet(df, top_left="A1", header=True):
            """Write a pandas DataFrame to the sheet starting at ``top_left``."""
            from ..core.reference import parse_a1

            r0, c0 = parse_a1(top_left)
            sh = doc.workbook.sheet
            r = r0
            if header:
                for j, name in enumerate(df.columns):
                    sh.set_cell(r, c0 + j, str(name))
                r += 1
            for i in range(len(df)):
                for j, v in enumerate(df.iloc[i]):
                    sh.set_cell(r + i, c0 + j, "" if v is None else str(v))
            win.refresh_table()

        from ..core import (
            algebraic,
            bayes,
            cluster,
            complexnum,
            eigen,
            fft,
            filters,
            financial,
            gmm,
            interp,
            matrix,
            metrics,
            ml,
            numeric,
            ode,
            ode_implicit,
            resynth,
            signal,
            spectral,
            stats,
            ti_engine,
            trees,
            units,
        )
        from ..core.graphing import compile_expr
        from ..core.rpn import RPN

        def _opt(expr):            # import a scientific package if present
            try:
                return __import__(expr)
            except Exception:
                return None

        _np = _opt("numpy")
        _pd = _opt("pandas")
        _scipy = _opt("scipy")
        _sklearn = _opt("sklearn")
        _pingouin = _opt("pingouin")
        # pymc/scikit-survival pull heavy backends (pytensor) — keep them lazy so
        # they only import when first touched, not on console open.
        _pymc = _LazyModule("pymc")
        _sksurv = _LazyModule("sksurv")
        try:
            import statsmodels.api as _sm
        except Exception:
            _sm = None

        return {
            "doc": doc,
            "wb": doc.workbook,
            "sheet": sheet,
            "cell": cell,
            "put": put,
            "refresh": refresh,
            "rpn": RPN(),
            # engineering toolkit
            "matrix": matrix,
            "eigen": eigen,
            "units": units,
            "numeric": numeric,
            "complexnum": complexnum,
            "fft": fft,
            "interp": interp,
            "signal": signal,
            "spectral": spectral,
            "filters": filters,
            "ode": ode,
            "ode_implicit": ode_implicit,
            "resynth": resynth,
            "stats": stats,
            "cluster": cluster,
            "ml": ml,
            "trees": trees,
            "bayes": bayes,
            "metrics": metrics,
            "gmm": gmm,
            "financial": financial,
            "algebraic": algebraic,
            "ti_engine": ti_engine,
            "np": _np,
            "numpy": _np,
            "pd": _pd,
            "pandas": _pd,
            "scipy": _scipy,
            "sm": _sm,
            "statsmodels": _sm,
            "sklearn": _sklearn,
            "pingouin": _pingouin,
            "pg": _pingouin,
            "pymc": _pymc,
            "pm": _pymc,
            "sksurv": _sksurv,
            "compile_expr": compile_expr,
            "read_matrix": read_matrix,
            "write_matrix": write_matrix,
            "sheet_to_df": sheet_to_df,
            "df_to_sheet": df_to_sheet,
            "__name__": "qcell_console",
        }

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._out = QPlainTextEdit(self)
        self._out.setReadOnly(True)
        self._out.setFont(mono)
        self._out.setPlainText(
            "qcell Python console. Namespace: doc, wb, sheet(), cell(ref), "
            "put(ref, val), rpn, refresh(); engineering: matrix, eigen, units, "
            "numeric, complexnum, fft, interp, signal, spectral, filters, ode, "
            "ode_implicit, resynth, stats, cluster, ml, trees, bayes, metrics, gmm, "
            "compile_expr, read_matrix(rng), write_matrix(cell, mat), "
            "sheet_to_df(rng), df_to_sheet(df, cell); data science (if installed): "
            "np/numpy, pd/pandas, scipy, sm/statsmodels, sklearn, pg/pingouin, "
            "pm/pymc, sksurv.\n>>> "
        )
        layout.addWidget(self._out)
        self._in = QLineEdit(self)
        self._in.setFont(mono)
        self._in.returnPressed.connect(self._run)
        layout.addWidget(self._in)

    def _run(self) -> None:
        src = self._in.text()
        self._in.clear()
        self._out.appendPlainText(src)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                self._interpreter().runsource(src, "<console>")
        except Exception as exc:  # pragma: no cover - defensive
            buf.write(f"{type(exc).__name__}: {exc}\n")
        out = buf.getvalue()
        if out:
            self._out.appendPlainText(out.rstrip("\n"))
        self._out.appendPlainText(">>> ")
        self._win.refresh_table()  # reflect any cell writes
        self._win._doc.mark_dirty()
