"""Tema uyumlu, bitişik ok düğmeli sayı alanı."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

_STEPPER_W = 32
_ARROW_SIZE = 12


def _arrow_icon(up: bool, color: str = "#cbd5e1") -> QIcon:
    pix = QPixmap(_ARROW_SIZE, _ARROW_SIZE)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    cx = _ARROW_SIZE // 2
    if up:
        painter.drawLine(cx - 4, cx + 1, cx, cx - 3)
        painter.drawLine(cx, cx - 3, cx + 4, cx + 1)
    else:
        painter.drawLine(cx - 4, cx - 3, cx, cx + 1)
        painter.drawLine(cx, cx + 1, cx + 4, cx - 3)
    painter.end()
    return QIcon(pix)


class StepperSpinBox(QWidget):
    """QSpinBox + sağda bitişik yukarı/aşağı ok düğmeleri."""

    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("stepperSpinBox")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._spin = QSpinBox()
        self._spin.setObjectName("stepperSpinInput")
        self._spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._spin.setFrame(False)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._spin.valueChanged.connect(self.valueChanged)

        stepper = QFrame()
        stepper.setObjectName("stepperSpinButtons")
        stepper.setFixedWidth(_STEPPER_W)
        stepper.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        stepper_layout = QVBoxLayout(stepper)
        stepper_layout.setContentsMargins(0, 0, 0, 0)
        stepper_layout.setSpacing(0)

        self._up_btn = QToolButton()
        self._up_btn.setObjectName("stepperSpinUp")
        self._up_btn.setAutoRepeat(True)
        self._up_btn.setAutoRepeatDelay(280)
        self._up_btn.setAutoRepeatInterval(55)
        self._up_btn.setIcon(_arrow_icon(True))
        self._up_btn.setIconSize(QSize(_ARROW_SIZE, _ARROW_SIZE))
        self._up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._up_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._up_btn.clicked.connect(self._spin.stepUp)

        self._down_btn = QToolButton()
        self._down_btn.setObjectName("stepperSpinDown")
        self._down_btn.setAutoRepeat(True)
        self._down_btn.setAutoRepeatDelay(280)
        self._down_btn.setAutoRepeatInterval(55)
        self._down_btn.setIcon(_arrow_icon(False))
        self._down_btn.setIconSize(QSize(_ARROW_SIZE, _ARROW_SIZE))
        self._down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._down_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._down_btn.clicked.connect(self._spin.stepDown)

        stepper_layout.addWidget(self._up_btn, 1)
        stepper_layout.addWidget(self._down_btn, 1)

        layout.addWidget(self._spin, 1)
        layout.addWidget(stepper)

    def spin_box(self) -> QSpinBox:
        return self._spin

    def setRange(self, minimum: int, maximum: int) -> None:
        self._spin.setRange(minimum, maximum)

    def setValue(self, value: int) -> None:
        self._spin.setValue(value)

    def value(self) -> int:
        return self._spin.value()

    def setSuffix(self, suffix: str) -> None:
        self._spin.setSuffix(suffix)

    def setSingleStep(self, step: int) -> None:
        self._spin.setSingleStep(step)

    def setAlignment(self, alignment: Qt.AlignmentFlag) -> None:
        self._spin.setAlignment(alignment)

    def setToolTip(self, tip: str) -> None:
        super().setToolTip(tip)
        self._spin.setToolTip(tip)
