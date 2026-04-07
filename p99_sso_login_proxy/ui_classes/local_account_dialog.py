from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)


class LocalAccountDialog(QDialog):
    """Dialog for adding or editing local accounts"""

    def __init__(self, parent=None, title="Local Account", account_name="", password="", aliases=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)

        self.account_name = QLineEdit(account_name)
        self.account_name.setPlaceholderText("myaccount1")
        self.account_name.setMinimumWidth(250)

        self.password = QLineEdit(password)
        self.password.setPlaceholderText("myPassword1")
        self.password.setMinimumWidth(250)

        self.aliases = QLineEdit(aliases)
        self.aliases.setPlaceholderText("alias1, alias2")
        self.aliases.setMinimumWidth(250)

        form.addRow("Account Name:", self.account_name)
        form.addRow("Password:", self.password)
        form.addRow("Aliases:", self.aliases)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setDefault(True)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(form)
        main_layout.addWidget(buttons)

        self.resize(400, self.sizeHint().height())
