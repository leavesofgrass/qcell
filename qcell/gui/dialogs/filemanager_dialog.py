"""Dual-pane file manager — a Worker / Directory Opus-style browser.

Two independent panes side by side; operations act on the *active* pane's
selection with the *other* pane as the target (the classic two-pane workflow).
A toolbar offers copy/move/delete/new-folder/rename/refresh, one-click
zip/tar.gz creation and extraction, and recursive find; a second row holds the
configurable command buttons (:mod:`qcell.core.fmbuttons`). All the heavy lifting
is the pure-stdlib core (:mod:`qcell.core.fileops` / ``archive`` / ``filesearch``),
so this file is just wiring and Qt.
"""

from __future__ import annotations

import os
import time

from .._qtcompat import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from ...core import archive, filesearch, fmbuttons
from ...core import fileops as F


class _Pane(QWidget):
    """One directory view: address bar, an Up button, and a file table."""

    def __init__(self, start_dir: str, on_active) -> None:
        super().__init__()
        self._dir = os.path.abspath(start_dir)
        self._on_active = on_active
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        bar = QHBoxLayout()
        self._up = QPushButton("Up", self)
        self._up.clicked.connect(self.go_up)
        self._address = QLineEdit(self._dir, self)
        self._address.returnPressed.connect(self._address_entered)
        bar.addWidget(self._up)
        bar.addWidget(self._address, 1)
        layout.addLayout(bar)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Name", "Size", "Modified"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.cellDoubleClicked.connect(self._activated)
        self._table.itemSelectionChanged.connect(lambda: self._on_active(self))
        layout.addWidget(self._table, 1)
        self.refresh()

    # --- state ----------------------------------------------------------
    def current_dir(self) -> str:
        return self._dir

    def selected_paths(self) -> list[str]:
        rows = sorted({i.row() for i in self._table.selectedItems()})
        out = []
        for r in rows:
            item = self._table.item(r, 0)
            if item is not None:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def set_dir(self, path: str) -> None:
        path = os.path.abspath(path)
        if os.path.isdir(path):
            self._dir = path
            self._address.setText(path)
            self.refresh()
            self._on_active(self)

    def go_up(self) -> None:
        self.set_dir(os.path.dirname(self._dir.rstrip(os.sep)) or self._dir)

    def select_names(self, names) -> None:
        """Test/programmatic helper: select rows by entry name."""
        wanted = set(names)
        self._table.clearSelection()
        for r in range(self._table.rowCount()):
            item = self._table.item(r, 0)
            if item is not None and os.path.basename(
                    item.data(Qt.ItemDataRole.UserRole)) in wanted:
                # set each cell selected (selectRow would *replace* the selection
                # in extended-selection mode, dropping earlier rows)
                for c in range(self._table.columnCount()):
                    cell = self._table.item(r, c)
                    if cell is not None:
                        cell.setSelected(True)

    def refresh(self) -> None:
        try:
            entries = F.list_dir(self._dir)
        except OSError as exc:
            QMessageBox.warning(self, "File manager", str(exc))
            return
        self._table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            name = QTableWidgetItem(("[ ] " if e.is_dir else "") + e.name)
            name.setData(Qt.ItemDataRole.UserRole, e.path)
            size = QTableWidgetItem("<dir>" if e.is_dir else F.human_size(e.size))
            mod = QTableWidgetItem(time.strftime("%Y-%m-%d %H:%M",
                                                 time.localtime(e.mtime)))
            self._table.setItem(r, 0, name)
            self._table.setItem(r, 1, size)
            self._table.setItem(r, 2, mod)

    # --- interaction ----------------------------------------------------
    def _address_entered(self) -> None:
        self.set_dir(self._address.text())

    def _activated(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if os.path.isdir(path):
            self.set_dir(path)


class FileManagerDialog(QDialog):
    def __init__(self, window=None, start_dir: str | None = None) -> None:
        super().__init__(window)
        self.setWindowTitle("File manager")
        self.resize(900, 540)
        self._win = window
        start = start_dir or os.getcwd()

        root = QVBoxLayout(self)
        root.addLayout(self._build_toolbar())

        self.left = _Pane(start, self._set_active)
        self.right = _Pane(start, self._set_active)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(self.left)
        split.addWidget(self.right)
        split.setSizes([450, 450])
        root.addWidget(split, 1)

        self._active = self.left
        root.addLayout(self._build_command_buttons())
        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(110)
        self._output.setPlaceholderText("command output")
        root.addWidget(self._output)
        self._status = QLabel("", self)
        root.addWidget(self._status)

    # --- layout ---------------------------------------------------------
    def _build_toolbar(self):
        bar = QHBoxLayout()
        for label, slot in (
            ("Refresh", self.refresh_both),
            ("New folder", self._new_folder),
            ("Rename", self._rename),
            ("Copy ->", self._copy),
            ("Move ->", self._move),
            ("Delete", self._delete),
            ("Zip", lambda: self._archive(".zip")),
            ("Tar.gz", lambda: self._archive(".tar.gz")),
            ("Extract", self._extract),
            ("Find", self._find),
        ):
            btn = QPushButton(label, self)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        bar.addStretch(1)
        return bar

    def _build_command_buttons(self):
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Commands:", self))
        self._buttons = fmbuttons.default_buttons()
        for b in self._buttons:
            btn = QPushButton(b.label, self)
            btn.setToolTip(b.command)
            btn.clicked.connect(lambda _=False, bb=b: self._run_button(bb))
            bar.addWidget(btn)
        bar.addStretch(1)
        return bar

    # --- helpers --------------------------------------------------------
    def _set_active(self, pane: _Pane) -> None:
        self._active = pane

    def _other(self, pane: _Pane) -> _Pane:
        return self.right if pane is self.left else self.left

    def refresh_both(self) -> None:
        self.left.refresh()
        self.right.refresh()

    def _set_status(self, msg: str) -> None:
        self._status.setText(msg)

    def _context(self) -> fmbuttons.Context:
        return fmbuttons.Context(
            directory=self._active.current_dir(),
            selection=self._active.selected_paths(),
            dest_dir=self._other(self._active).current_dir())

    # --- operations -----------------------------------------------------
    def _copy(self) -> None:
        dest = self._other(self._active).current_dir()
        res = F.copy_paths(self._active.selected_paths(), dest)
        self.refresh_both()
        self._set_status("copied: " + res.summary())

    def _move(self) -> None:
        dest = self._other(self._active).current_dir()
        res = F.move_paths(self._active.selected_paths(), dest)
        self.refresh_both()
        self._set_status("moved: " + res.summary())

    def _delete(self) -> None:
        paths = self._active.selected_paths()
        if not paths:
            return
        if QMessageBox.question(self, "Delete",
                                f"Delete {len(paths)} item(s)?") \
                != QMessageBox.StandardButton.Yes:
            return
        res = F.delete_paths(paths)
        self.refresh_both()
        self._set_status("deleted: " + res.summary())

    def _new_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "New folder", "Name:")
        if ok and name:
            try:
                F.make_dir(self._active.current_dir(), name)
            except OSError as exc:
                QMessageBox.warning(self, "New folder", str(exc))
            self._active.refresh()

    def _rename(self) -> None:
        sel = self._active.selected_paths()
        if not sel:
            return
        old = os.path.basename(sel[0])
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        if ok and name and name != old:
            try:
                F.rename_path(sel[0], name)
            except OSError as exc:
                QMessageBox.warning(self, "Rename", str(exc))
            self._active.refresh()

    def _archive(self, ext: str) -> None:
        sel = self._active.selected_paths()
        if not sel:
            self._set_status("nothing selected to archive")
            return
        default = os.path.join(self._active.current_dir(), "archive" + ext)
        dest, _ = QFileDialog.getSaveFileName(self, "Create archive", default)
        if not dest:
            return
        try:
            archive.create_archive(sel, dest)
        except (OSError, archive.ArchiveError) as exc:
            QMessageBox.warning(self, "Archive", str(exc))
            return
        self.refresh_both()
        self._set_status(f"created {os.path.basename(dest)}")

    def _extract(self) -> None:
        sel = self._active.selected_paths()
        if not sel:
            return
        dest = self._other(self._active).current_dir()
        try:
            names = archive.extract_archive(sel[0], dest)
        except (OSError, archive.ArchiveError) as exc:
            QMessageBox.warning(self, "Extract", str(exc))
            return
        self.refresh_both()
        self._set_status(f"extracted {len(names)} item(s) -> {dest}")

    def _find(self) -> None:
        pattern, ok = QInputDialog.getText(
            self, "Find", "Name pattern (e.g. *.py):", text="*")
        if not ok or not pattern:
            return
        contains, ok2 = QInputDialog.getText(
            self, "Find", "Containing text (optional):")
        kw = {"name_glob": pattern}
        if ok2 and contains:
            kw["contains"] = contains
        hits = filesearch.search(self._active.current_dir(), **kw)
        self._show_results(hits)

    def _show_results(self, hits) -> None:
        from .._qtcompat import QListWidget

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Find results ({len(hits)})")
        dlg.resize(700, 400)
        lay = QVBoxLayout(dlg)
        lst = QListWidget(dlg)
        for m in hits:
            label = m.path + (f":{m.line_no}: {m.line.strip()}" if m.line_no else "")
            lst.addItem(label)
        lay.addWidget(lst)

        def jump():
            row = lst.currentRow()
            if 0 <= row < len(hits):
                folder = os.path.dirname(hits[row].path)
                self._active.set_dir(folder)
                self._active.select_names([os.path.basename(hits[row].path)])
                dlg.accept()

        lst.itemDoubleClicked.connect(jump)
        dlg.exec()

    def _run_button(self, button: fmbuttons.Button) -> None:
        if button.confirm and QMessageBox.question(
                self, button.label, f"Run: {button.command}?") \
                != QMessageBox.StandardButton.Yes:
            return
        res = fmbuttons.run_button(button, self._context(), timeout=60)
        self.refresh_both()
        out = (res.stdout or res.stderr or "").rstrip()
        # Non-modal: command output goes to the output pane, not a blocking popup.
        self._output.appendPlainText(f"$ {res.command}")
        if out:
            self._output.appendPlainText(out[:8000])
        self._set_status(f"{button.label}: exit {res.returncode}")
