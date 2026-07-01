"""Ensure the project root is importable when running tests uninstalled, and
dispose any leaked Qt windows between tests so the GUI suite stays safe in a
long-lived process."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _dispose_leaked_qt_windows():
    """Delete any top-level Qt widget still alive at the end of a test.

    The GUI tests build a ``MainWindow`` per test; the fixtures now dispose their
    own window, but a few tests create one via a plain helper (a local variable,
    dropped when the test returns) and would otherwise pile up. Left alone, dozens
    of live windows make a later test that restyles the whole widget tree (the
    zoom test's repeated global ``setStyleSheet``) crawl or crash Qt.

    Being autouse, this tears down *after* the per-test fixtures, so a fixture has
    already deleted its own window before we look — we only ever collect the
    genuine strays, never a window another fixture still owns.

    A cheap no-op for the ~700 non-GUI tests: it acts only when the Qt binding has
    actually been imported in this worker (a plain ``sys.modules`` lookup — no Qt
    import is forced)."""
    yield
    qt = sys.modules.get("abax.gui._qtcompat")
    if qt is None:
        return
    app = qt.QApplication.instance()
    if app is None:
        return
    for widget in list(app.topLevelWidgets()):
        widget.deleteLater()
    app.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)
    app.processEvents()
