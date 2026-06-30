"""Antenna pattern viewer — a QPainter polar plot of the analytic patterns from
:mod:`qcell.core.science.antenna` (Phase A), with directivity / beamwidth readout.

Pick a half-wave or full-wave dipole, or a uniform linear array (set N, element
spacing in wavelengths, and progressive phase). The E-plane pattern is drawn with
the antenna axis vertical (nulls top/bottom for a dipole).
"""

from __future__ import annotations

import math

from .._qtcompat import (
    QColor,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPainter,
    QPainterPath,
    QPen,
    QPointF,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PolarPlot(QWidget):
    """Polar plot of ``[(theta, magnitude 0..1)]`` samples (theta from the vertical)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self._samples: list = []

    def set_samples(self, samples: list) -> None:
        self._samples = list(samples)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        radius = min(w, h) / 2.0 - 16.0
        cx, cy = w / 2.0, h / 2.0
        grid = self.palette().windowText().color()

        faint = QColor(grid)
        faint.setAlpha(90)
        p.setPen(QPen(faint, 1.0))
        for frac in (0.25, 0.5, 0.75, 1.0):
            p.drawEllipse(QPointF(cx, cy), radius * frac, radius * frac)
        for deg in range(0, 360, 30):
            a = math.radians(deg)
            p.drawLine(QPointF(cx, cy),
                       QPointF(cx + radius * math.sin(a), cy - radius * math.cos(a)))

        if self._samples:
            p.setPen(QPen(self.palette().highlight().color(), 2.0))
            path = QPainterPath()
            for i, (th, mag) in enumerate(self._samples):
                x = cx + mag * radius * math.sin(th)
                y = cy - mag * radius * math.cos(th)
                (path.moveTo if i == 0 else path.lineTo)(QPointF(x, y))
            path.closeSubpath()
            p.drawPath(path)
        p.end()


class AntennaDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self._win = window
        self.setWindowTitle("Antenna pattern")
        self.resize(580, 440)
        self._build()
        self._plot()

    def _build(self) -> None:
        outer = QHBoxLayout(self)
        self._plotw = PolarPlot(self)
        outer.addWidget(self._plotw, 1)

        side = QVBoxLayout()
        form = QFormLayout()
        self._kind = QComboBox(self)
        self._kind.addItems(["Half-wave dipole", "Full-wave dipole", "Linear array"])
        self._kind.currentIndexChanged.connect(self._plot)
        self._n = QLineEdit("4", self)
        self._spacing = QLineEdit("0.5", self)
        self._phase = QLineEdit("0", self)
        form.addRow("Pattern:", self._kind)
        form.addRow("Array N:", self._n)
        form.addRow("Spacing (λ):", self._spacing)
        form.addRow("Phase (°):", self._phase)
        side.addLayout(form)
        btn = QPushButton("Plot", self)
        btn.clicked.connect(self._plot)
        side.addWidget(btn)
        self._readout = QLabel(self)
        self._readout.setWordWrap(True)
        side.addWidget(self._readout, 1)
        outer.addLayout(side)

    def field_fn(self):
        """The selected pattern's field function (UI-free; testable)."""
        from ...core.science import antenna

        i = self._kind.currentIndex()
        if i == 0:
            return antenna.half_wave_dipole()
        if i == 1:
            return antenna.full_wave_dipole()
        n = max(1, int(float(self._n.text())))
        return antenna.linear_array(n, float(self._spacing.text()), float(self._phase.text()))

    def _plot(self) -> None:
        from ...core.science import antenna

        try:
            f = self.field_fn()
        except ValueError:
            self._readout.setText("Array N / spacing / phase must be numbers.")
            return
        self._plotw.set_samples(antenna.pattern_samples(f, count=361))
        self._readout.setText(
            f"Directivity: {antenna.gain_dbi(f):.2f} dBi\n"
            f"Half-power beamwidth: {antenna.half_power_beamwidth(f):.1f}°")
