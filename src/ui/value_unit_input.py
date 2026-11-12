"""Validated numeric input with an optional, always visible unit selector."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from PySide6.QtCore import Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget


@dataclass(frozen=True)
class UnitSpec:
    label: str
    factor: float  # Displayed amount multiplied by this gives the stored base amount.


class ValueUnitInput(QWidget):
    """Store base units; setValue always selects the declared default display unit.

    Unit changes preserve the rounded base value. An empty unit list gives a
    unitless number field with the same validation and error presentation.
    """

    valueChanged = Signal(object)
    _NUMBER = re.compile(r"\+?(?:\d+(?:\.\d*)?|\.\d+)")

    def __init__(self, units, minimum, maximum, decimals=0, default_unit=0, parent=None):
        super().__init__(parent)
        self.units = tuple(units)
        if not self.units:
            self.units = ()
            default_unit = 0
        if any(not u.label or Decimal(str(u.factor)) <= 0 for u in self.units):
            raise ValueError("Units need a label and a positive factor")
        if not 0 <= default_unit < max(1, len(self.units)):
            raise ValueError("Invalid default unit")
        if minimum > maximum or decimals < 0:
            raise ValueError("Invalid numeric range")
        self.minimum = Decimal(str(minimum))
        self.maximum = Decimal(str(maximum))
        self.decimals = decimals
        self.default_unit = default_unit
        self._unit_index = default_unit
        self._last_value = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.number_edit = QLineEdit(self)
        self.number_edit.setObjectName("valueUnitNumber")
        validator = QDoubleValidator(0, 1e12, 10, self.number_edit)
        validator.setNotation(QDoubleValidator.StandardNotation)
        self.number_edit.setValidator(validator)
        layout.addWidget(self.number_edit, 1)

        self.unit_combo = None
        if self.units:
            self.unit_combo = QComboBox(self)
            self.unit_combo.setObjectName("valueUnitCombo")
            for unit in self.units:
                self.unit_combo.addItem(unit.label)
            self.unit_combo.setCurrentIndex(default_unit)
            # Include text, line-edit padding and the styled drop-down subcontrol.
            longest = max(self.unit_combo.fontMetrics().horizontalAdvance(u.label) for u in self.units)
            self.unit_combo.setFixedWidth(longest + 90)
            layout.addWidget(self.unit_combo)
            self.unit_combo.currentIndexChanged.connect(self._change_unit)
        self.number_edit.textChanged.connect(self._text_changed)
        self._refresh_validation()

    def _factor(self, index=None):
        index = self._unit_index if index is None else index
        return Decimal(str(self.units[index].factor)) if self.units else Decimal(1)

    def _rounded(self, amount):
        quantum = Decimal(1).scaleb(-self.decimals)
        return amount.quantize(quantum, rounding=ROUND_HALF_UP)

    def _base_value(self, index=None):
        raw = self.number_edit.text().strip()
        if not self._NUMBER.fullmatch(raw):
            raise ValueError("请输入有效数字")
        try:
            amount = self._rounded(Decimal(raw) * self._factor(index))
        except (InvalidOperation, OverflowError):
            raise ValueError("请输入有效数字") from None
        if not amount.is_finite():
            raise ValueError("请输入有效数字")
        if not self.minimum <= amount <= self.maximum:
            raise ValueError(self._range_text(index))
        return int(amount) if self.decimals == 0 else float(amount)

    def _display(self, base, index):
        # Ten fractional digits cover minute conversions of integer seconds;
        # converting back then rounds to the declared base precision.
        display = Decimal(str(base)) / self._factor(index)
        display = display.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
        return format(display.normalize(), "f")

    def _range_text(self, index=None):
        unit = f" {self.units[index if index is not None else self._unit_index].label}" if self.units else ""
        low = self._display(self.minimum, index if index is not None else self._unit_index)
        high = self._display(self.maximum, index if index is not None else self._unit_index)
        return f"允许范围：{low}–{high}{unit}"

    def _refresh_validation(self):
        error = self.errorText()
        invalid = bool(error)
        if self.number_edit.property("invalid") != invalid:
            self.number_edit.setProperty("invalid", invalid)
            self.number_edit.style().unpolish(self.number_edit)
            self.number_edit.style().polish(self.number_edit)
            self.number_edit.update()
        self.number_edit.setToolTip(self._range_text() if invalid else "")
        return not invalid

    def _text_changed(self):
        if self._refresh_validation():
            current = self.value()
            if current != self._last_value:
                self._last_value = current
                self.valueChanged.emit(current)

    def _change_unit(self, index):
        if index == self._unit_index or index < 0:
            return
        try:
            base = self._base_value(self._unit_index)
        except ValueError:
            self.unit_combo.blockSignals(True)
            self.unit_combo.setCurrentIndex(self._unit_index)
            self.unit_combo.blockSignals(False)
            self._refresh_validation()
            return
        self._unit_index = index
        self.number_edit.setText(self._display(base, index))
        self._refresh_validation()

    def value(self):
        """Return the rounded stored value, or raise ValueError for invalid input."""
        return self._base_value()

    def setValue(self, base_value):
        self._unit_index = self.default_unit
        if self.unit_combo is not None:
            self.unit_combo.blockSignals(True)
            self.unit_combo.setCurrentIndex(self.default_unit)
            self.unit_combo.blockSignals(False)
        self.number_edit.setText(self._display(base_value, self.default_unit))
        self._refresh_validation()

    def isValid(self):
        return not self.errorText()

    def errorText(self):
        try:
            self._base_value()
        except ValueError as error:
            return str(error)
        return ""
