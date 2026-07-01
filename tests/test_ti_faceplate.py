"""TI faceplate ALPHA letter entry (variables via the on-screen keypad)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("abax.gui._qtcompat")

from abax.gui._qtcompat import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def fp(app):
    from abax.gui.calc.ti_faceplate import TIFaceplate

    return TIFaceplate()


def test_alpha_one_shot_types_letter(fp):
    fp._do("@alpha")
    assert fp.alpha == "on"
    fp._press("@math", None)          # ALPHA + MATH -> A
    assert fp.input == "A"
    assert fp.alpha == ""             # one-shot cleared


def test_alpha_lock_types_multiple(fp):
    fp._do("@alpha")
    fp._do("@alpha")                  # second press -> A-LOCK
    assert fp.alpha == "lock"
    fp._press("@apps", None)          # B
    fp._press("@prgm", None)          # C
    assert fp.input == "BC"


def test_store_and_recall_via_alpha(fp):
    # Build "5->A" from the keypad: 5, STO> (inserts ->), ALPHA, MATH (A).
    for ch in "5":
        fp._press(ch, None)
    fp._press("@sto", None)           # normal mode -> the store arrow
    fp._do("@alpha")
    fp._press("@math", None)          # A
    assert fp.input == "5->A"
    fp._do("@enter")
    assert fp.engine.get_var("A") == 5.0
    # recall A in an expression
    fp._do("@alpha")
    fp._press("@math", None)          # A
    for ch in ["*", "3"]:
        fp._press(ch, None)
    fp._do("@enter")
    assert fp.engine.history()[-1] == ("A*3", "15")


def test_alpha_sto_key_gives_x(fp):
    # ALPHA + STO> is the letter X (not the store arrow).
    fp._do("@alpha")
    fp._press("@sto", None)
    assert fp.input == "X"


def test_non_letter_cancels_one_shot_alpha(fp):
    fp._do("@alpha")
    fp._press("@enter", None)         # ENTER has no letter -> cancels ALPHA
    assert fp.alpha == ""
