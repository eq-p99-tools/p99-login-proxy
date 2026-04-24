"""Add/Edit dialog for a local character row."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from p99_sso_login_proxy import class_translate, config, zone_translate
from p99_sso_login_proxy.theme import semantic

CLASS_CHOICES: tuple[str, ...] = tuple(sorted(class_translate.CLASSES))

_BOOL_ITEM_LABELS = {
    "seb": "Trakanon Idol (Seb key)",
    "vp": "Key of Veeshan",
    "st": "Sleeper's Key",
    "void": "Box of the Void",
    "neck": "Necklace of Resolution",
    "thurg": "Vial of Velium Vapors",
    "reaper": "Reaper of the Dead",
    "brass_idol": "Shiny Brass Idol",
}
_COUNT_ITEM_LABELS = {
    "lizard": "Lizard Blood Potion",
    "pearl": "Pearl",
    "peridot": "Peridot",
    "mb3": "Mana Battery III",
    "mb4": "Mana Battery IV",
    "mb5": "Mana Battery V",
}


def _zone_completion_strings() -> list[str]:
    """Return a sorted list of zonekeys and pretty zone names for completer suggestions."""
    values: set[str] = set()
    values.update(zone_translate.zone_aliases.keys())
    values.update(zone_translate.zonekey_to_alias.keys())
    return sorted(v for v in values if v)


def _normalize_zone(text: str) -> str:
    """Convert user text to a zonekey; accepts either display name or zonekey."""
    text = (text or "").strip()
    if not text:
        return ""
    return zone_translate.zone_to_zonekey(text) or text.lower()


class LocalCharacterDialog(QDialog):
    """Dialog for adding or editing a local character."""

    def __init__(
        self,
        parent=None,
        *,
        title: str = "Local Character",
        name: str = "",
        account: str = "",
        klass: str | None = None,
        level: int | None = None,
        bind: str | None = None,
        park: str | None = None,
        items: dict | None = None,
        lock_name: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("CharName")
        self.name_edit.setMinimumWidth(220)
        if lock_name:
            self.name_edit.setReadOnly(True)
            self.name_edit.setToolTip("Character name cannot be changed when editing.")
            name_font = self.name_edit.font()
            name_font.setItalic(True)
            self.name_edit.setFont(name_font)
            self.name_edit.setStyleSheet(
                f"background-color: {semantic.alt_row.name()};"
                f"color: {semantic.muted.name()};"
                "border: 1px solid #555;"
                "border-radius: 3px;"
                "padding: 2px 6px;"
            )

        self.account_combo = QComboBox()
        self.account_combo.setEditable(True)
        self.account_combo.addItem("")
        for acc in sorted(config.LOCAL_ACCOUNTS):
            self.account_combo.addItem(acc)
        if account:
            idx = self.account_combo.findText(account)
            if idx >= 0:
                self.account_combo.setCurrentIndex(idx)
            else:
                self.account_combo.setEditText(account)

        self.class_combo = QComboBox()
        self.class_combo.addItem("")
        for cls in CLASS_CHOICES:
            self.class_combo.addItem(cls)
        if klass:
            idx = self.class_combo.findText(klass)
            if idx >= 0:
                self.class_combo.setCurrentIndex(idx)

        self.level_spin = QSpinBox()
        self.level_spin.setRange(0, 65)
        self.level_spin.setSpecialValueText(" ")  # show blank when value == minimum
        self.level_spin.setValue(level if level is not None else 0)

        zone_completer = QCompleter(_zone_completion_strings(), self)
        zone_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        zone_completer.setFilterMode(Qt.MatchFlag.MatchContains)

        def _zone_edit(initial: str | None) -> QLineEdit:
            edit = QLineEdit(zone_translate.zonekey_to_zone(initial) if initial else "")
            edit.setPlaceholderText("e.g. North Karana or nro")
            edit.setMinimumWidth(220)
            edit.setCompleter(zone_completer)
            return edit

        self.bind_edit = _zone_edit(bind)
        self.park_edit = _zone_edit(park)

        form.addRow("Character Name:", self.name_edit)
        form.addRow("Account:", self.account_combo)
        form.addRow("Class:", self.class_combo)
        form.addRow("Level:", self.level_spin)
        form.addRow("Bind Location:", self.bind_edit)
        form.addRow("Park Location:", self.park_edit)

        items = items or {}
        self._bool_checks: dict[str, QCheckBox] = {}
        self._count_edits: dict[str, QLineEdit] = {}

        self.items_group = QGroupBox("Items (optional — usually populated automatically)")
        self.items_group.setCheckable(True)
        self.items_group.setChecked(False)
        items_layout = QGridLayout()
        items_layout.setHorizontalSpacing(12)
        items_layout.setVerticalSpacing(4)

        row = 0
        items_layout.addWidget(self._section_label("Keys / Flags"), row, 0, 1, 2)
        row += 1
        for wk, label in _BOOL_ITEM_LABELS.items():
            cb = QCheckBox(label)
            cb.setTristate(True)
            current = items.get(wk)
            if current is True:
                cb.setCheckState(Qt.CheckState.Checked)
            elif current is False:
                cb.setCheckState(Qt.CheckState.Unchecked)
            else:
                cb.setCheckState(Qt.CheckState.PartiallyChecked)
            cb.setToolTip("Tri-state: checked = yes, unchecked = no, partial = unknown")
            self._bool_checks[wk] = cb
            items_layout.addWidget(cb, row, 0, 1, 2)
            row += 1

        items_layout.addWidget(self._section_label("Stack Counts"), row, 0, 1, 2)
        row += 1
        int_validator = QIntValidator(0, 999, self)
        for wk, label in _COUNT_ITEM_LABELS.items():
            edit = QLineEdit()
            edit.setPlaceholderText("unknown")
            edit.setValidator(int_validator)
            edit.setMaximumWidth(80)
            current = items.get(wk)
            if isinstance(current, int):
                edit.setText(str(current))
            self._count_edits[wk] = edit
            items_layout.addWidget(QLabel(label), row, 0)
            items_layout.addWidget(edit, row, 1)
            row += 1

        self.items_group.setLayout(items_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setDefault(True)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(form)
        main_layout.addWidget(self.items_group)
        main_layout.addWidget(buttons)

        self.resize(460, self.sizeHint().height())

    @staticmethod
    def _section_label(text: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 6, 0, 2)
        lbl = QLabel(text)
        font = lbl.font()
        font.setBold(True)
        lbl.setFont(font)
        layout.addWidget(lbl)
        layout.addStretch(1)
        return container

    def get_result(self) -> dict:
        """Return the user-entered entry in the shape used by :mod:`local_characters`."""
        level_raw = self.level_spin.value()
        items: dict[str, bool | int | None] = {}
        for wk, cb in self._bool_checks.items():
            state = cb.checkState()
            if state == Qt.CheckState.Checked:
                items[wk] = True
            elif state == Qt.CheckState.Unchecked:
                items[wk] = False
            else:
                items[wk] = None
        for wk, edit in self._count_edits.items():
            text = edit.text().strip()
            if not text:
                items[wk] = None
            else:
                try:
                    items[wk] = int(text)
                except ValueError:
                    items[wk] = None
        return {
            "name": self.name_edit.text().strip(),
            "account": self.account_combo.currentText().strip().lower(),
            "class": self.class_combo.currentText().strip() or None,
            "level": level_raw if level_raw > 0 else None,
            "bind": _normalize_zone(self.bind_edit.text()) or None,
            "park": _normalize_zone(self.park_edit.text()) or None,
            "items": items,
        }
