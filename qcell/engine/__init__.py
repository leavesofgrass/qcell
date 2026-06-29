"""qcell.engine — adapters bridging the stdlib core to optional libraries.

The middle of the three-layer seam (core -> engine -> gui/tui). Code here may
import optional third-party packages (e.g. openpyxl) but always degrades
gracefully when they are absent.
"""

from .document import Document
from .excel_io import HAS_OPENPYXL, load_xlsx, save_xlsx

__all__ = ["HAS_OPENPYXL", "load_xlsx", "save_xlsx", "Document"]
