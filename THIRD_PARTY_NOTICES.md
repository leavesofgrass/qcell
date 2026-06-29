# Third-party notices, attribution & disclaimers

qcell is licensed under the **GNU General Public License v3.0 or later**
(see [`LICENSE`](LICENSE)). This file documents the third-party components qcell
can use, their licenses, and trademark disclaimers. qcell **bundles none** of the
binaries below — they are optional, declared dependencies the user installs, or
artifacts fetched on demand into the user's cache.

## Qt binding (GUI)

The desktop GUI runs on either Qt for Python binding; qcell imports neither
directly except through `qcell/gui/_qtcompat.py`.

| Component | License | Notes |
|-----------|---------|-------|
| **PySide6** (default) | LGPL-3.0 | Preferred binding; `pip install qcell[gui]`. |
| **PyQt6** (optional) | GPL-3.0 / commercial | `pip install qcell[gui-pyqt]`; set `QCELL_QT_BINDING=PyQt6`. |

GPL-3.0 (qcell) is compatible with both. qcell does not bundle Qt; the user
supplies it via pip.

## Optional Python dependencies

All optional and installed by the user; all GPL-compatible:

| Package | License | Used for |
|---------|---------|----------|
| openpyxl | MIT | Excel `.xlsx` import/export |
| msgspec | BSD-3-Clause | fast JSON I/O (stdlib `json` fallback) |
| platformdirs | MIT | cross-platform config/data/cache dirs (stdlib fallback) |
| textual | MIT | rich TUI (curses fallback) |
| rich | MIT | TUI rendering |

Other libraries (e.g. pandas) are used only if already present in the
environment; they are never required.

## Fetched-on-demand components

- **OpenDyslexic font** — SIL Open Font License 1.1. Fetched on demand from the
  upstream OpenDyslexic project into qcell's cache when the user enables the
  dyslexia-friendly font. qcell ships no font files. © the OpenDyslexic project;
  used under the OFL. <https://opendyslexic.org/>
- **pandoc** — GPL-2.0-or-later. Used only if present, or installed at the user's
  explicit request via the `pypandoc_binary` wheel, and invoked as a separate
  process for LaTeX → MathML. A pure-Python subset renderer is the fallback.

## Trademarks & calculator emulation

qcell includes RPN and algebraic calculator emulations. These reproduce
**functionality only**; qcell bundles no manufacturer artwork, ROMs, or branding.

- **HP**, **HP-12C**, **HP-15C**, **HP-16C** are trademarks of HP Inc. (or its
  affiliates). The built-in "Voyager" faceplate is an original, de-branded vector
  drawing; it uses no HP or Nonpareil artwork. An optional photographic faceplate
  reads **user-supplied** asset files from a directory the user configures
  (`QCELL_FACEPLATE_DIR` or settings) — qcell distributes none of those assets.
- **TI**, **TI-82**, **TI-83**, **TI-84** are trademarks of Texas Instruments.

qcell is an independent project and is **not affiliated with, authorized,
sponsored, or endorsed by** HP Inc. or Texas Instruments. Product and calculator
names are used descriptively to identify the emulated functionality.

## Attribution

Portions of the RPN/calculator engine and the de-branded faceplate are derived
from the author's own earlier calculator project and contributed to qcell under
qcell's license.
