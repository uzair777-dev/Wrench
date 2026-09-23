"""FR-5.6 / FR-8.1-8.5: Forge Accounts Management Dialogs."""

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench import credentials
from wrench.forge.capability import ForgeAdapter
from wrench.forge.models import ForgeAccount
from wrench.forge.registry import get_adapter_class
from wrench.storage import db, forge_accounts
from wrench.ui.workers import run_in_background

logger = logging.getLogger(__name__)

DEFAULT_URLS = {
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "bitbucket": "https://bitbucket.org",
    "forgejo": "https://codeberg.org",
}


def _validate_credentials_probe(
    provider: str,
    instance_url: str,
    token: str,
    username: str | None,
    tls_ca_bundle_path: str | None,
    tls_insecure: bool,
) -> dict[str, Any]:
    """Runs in background thread: probes provider endpoint with candidate credentials."""
    adapter_cls = get_adapter_class(provider)
    candidate_account = ForgeAccount(
        id=-1,
        provider=provider,
        instance_url=instance_url,
        label="probe",
        username=username,
        secret_service_key="",
        tls_ca_bundle_path=tls_ca_bundle_path,
        tls_insecure=tls_insecure,
    )
    adapter: ForgeAdapter = adapter_cls(candidate_account)
    adapter._cached_token = token
    try:
        resp = adapter._request("GET", "/user")
        data = resp.json() if resp.content else {}
        # Try to infer username if missing
        inferred_user = (
            data.get("login") or data.get("username") or data.get("nickname") or username
        )
        return {"ok": True, "inferred_user": inferred_user}
    finally:
        adapter.close()


class AddAccountDialog(QDialog):
    """Modal dialog to add and validate a new forge account."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Forge Account")
        self.setMinimumWidth(460)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Provider
        self.provider_combo = QComboBox(self)
        self.provider_combo.addItem("GitHub", "github")
        self.provider_combo.addItem("GitLab", "gitlab")
        self.provider_combo.addItem("Forgejo / Gitea", "forgejo")
        self.provider_combo.addItem("Bitbucket Cloud", "bitbucket")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provider:", self.provider_combo)

        # Instance URL
        self.url_edit = QLineEdit(self)
        self.url_edit.setText(DEFAULT_URLS["github"])
        form.addRow("Instance URL:", self.url_edit)

        # Label
        self.label_edit = QLineEdit(self)
        self.label_edit.setPlaceholderText("e.g. Work GitHub, Personal GitLab")
        form.addRow("Account Label:", self.label_edit)

        # Username
        self.username_edit = QLineEdit(self)
        self.username_edit.setPlaceholderText("Optional (required for Bitbucket)")
        form.addRow("Username / Email:", self.username_edit)

        # Token
        token_layout = QHBoxLayout()
        self.token_edit = QLineEdit(self)
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("Personal Access Token / App Password")
        token_layout.addWidget(self.token_edit)

        self.toggle_token_btn = QToolButton(self)
        self.toggle_token_btn.setText("👁")
        self.toggle_token_btn.setToolTip("Show / Hide Token")
        self.toggle_token_btn.clicked.connect(self._toggle_token_visibility)
        token_layout.addWidget(self.toggle_token_btn)
        form.addRow("Token / Secret:", token_layout)

        # TLS / Advanced Group
        self.tls_group = QGroupBox("TLS & Enterprise Security", self)
        tls_layout = QFormLayout(self.tls_group)

        ca_layout = QHBoxLayout()
        self.ca_edit = QLineEdit(self.tls_group)
        self.ca_edit.setPlaceholderText("Optional path to custom CA bundle (.pem)")
        ca_layout.addWidget(self.ca_edit)

        browse_btn = QPushButton("Browse…", self.tls_group)
        browse_btn.clicked.connect(self._browse_ca)
        ca_layout.addWidget(browse_btn)
        tls_layout.addRow("CA Bundle:", ca_layout)

        self.insecure_cb = QCheckBox(
            "Disable SSL/TLS certificate verification (Insecure)", self.tls_group
        )
        tls_layout.addRow("", self.insecure_cb)

        form.addRow(self.tls_group)
        layout.addLayout(form)

        # Status / Error Label
        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #d20f39; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Validate & Save", self)
        self.save_btn.setStyleSheet("font-weight: bold;")
        self.save_btn.clicked.connect(self._validate_and_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def _on_provider_changed(self) -> None:
        prov = self.provider_combo.currentData()
        self.url_edit.setText(DEFAULT_URLS.get(prov, "https://"))
        if prov == "bitbucket":
            self.username_edit.setPlaceholderText("Atlassian Account Email (Required)")
        else:
            self.username_edit.setPlaceholderText("Optional (inferred from token)")

    def _toggle_token_visibility(self) -> None:
        if self.token_edit.echoMode() == QLineEdit.Password:
            self.token_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.token_edit.setEchoMode(QLineEdit.Password)

    def _browse_ca(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CA Certificate Bundle",
            "",
            "Certificate Files (*.pem *.crt *.ca-bundle);;All Files (*)",
        )
        if file_path:
            self.ca_edit.setText(file_path)

    def _validate_and_save(self) -> None:
        prov = self.provider_combo.currentData()
        url = self.url_edit.text().strip().rstrip("/")
        label = self.label_edit.text().strip()
        username = self.username_edit.text().strip() or None
        token = self.token_edit.text().strip()
        ca_bundle = self.ca_edit.text().strip() or None
        insecure = self.insecure_cb.isChecked()

        if not url:
            self.status_label.setText("Error: Instance URL cannot be empty.")
            return
        if not token:
            self.status_label.setText("Error: Token cannot be empty.")
            return
        if prov == "bitbucket" and not username:
            self.status_label.setText(
                "Error: Bitbucket requires an Atlassian account email as username."
            )
            return

        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status_label.setStyleSheet("color: palette(text); font-size: 11px;")
        self.status_label.setText("Connecting and validating credentials…")

        run_in_background(
            fn=lambda: _validate_credentials_probe(prov, url, token, username, ca_bundle, insecure),
            on_finished=lambda res: self._on_validation_success(
                prov, url, label, username or res.get("inferred_user"), token, ca_bundle, insecure
            ),
            on_failed=self._on_validation_failure,
        )

    def _on_validation_success(
        self,
        provider: str,
        instance_url: str,
        label: str,
        username: str | None,
        token: str,
        ca_bundle: str | None,
        insecure: bool,
    ) -> None:
        if not label:
            user_suffix = f" ({username})" if username else ""
            label = f"{provider.capitalize()}{user_suffix}"

        conn = db.get_connection()
        try:
            forge_accounts.add_account(
                conn,
                provider=provider,
                instance_url=instance_url,
                label=label,
                username=username,
                token=token,
                tls_ca_bundle_path=ca_bundle,
                tls_insecure=insecure,
            )
        except Exception as exc:
            self.status_label.setStyleSheet("color: #d20f39; font-size: 11px;")
            self.status_label.setText(f"Failed to store account: {exc}")
            self.save_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            return
        finally:
            conn.close()

        self.accept()

    def _on_validation_failure(self, exc: Exception) -> None:
        self.save_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.status_label.setStyleSheet("color: #d20f39; font-size: 11px;")
        self.status_label.setText(f"Validation failed: {exc}")


class EditAccountDialog(QDialog):
    """Modal dialog to edit label, username, TLS settings, or update token."""

    def __init__(
        self, record: forge_accounts.ForgeAccountRecord, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.record = record
        self.setWindowTitle(f"Edit Account — {record.label}")
        self.setMinimumWidth(440)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()

        # Provider & URL (info)
        info_label = QLabel(
            f"<b>{self.record.provider.capitalize()}</b> at {self.record.instance_url}", self
        )
        form.addRow("Service:", info_label)

        # Label
        self.label_edit = QLineEdit(self)
        self.label_edit.setText(self.record.label)
        form.addRow("Account Label:", self.label_edit)

        # Username
        self.username_edit = QLineEdit(self)
        self.username_edit.setText(self.record.username or "")
        form.addRow("Username / Email:", self.username_edit)

        # New Token (Optional)
        token_layout = QHBoxLayout()
        self.token_edit = QLineEdit(self)
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("Leave blank to keep current token")
        token_layout.addWidget(self.token_edit)

        self.toggle_token_btn = QToolButton(self)
        self.toggle_token_btn.setText("👁")
        self.toggle_token_btn.clicked.connect(self._toggle_token_visibility)
        token_layout.addWidget(self.toggle_token_btn)
        form.addRow("Update Token:", token_layout)

        # TLS / Advanced Group
        tls_group = QGroupBox("TLS & Enterprise Security", self)
        tls_layout = QFormLayout(tls_group)

        ca_layout = QHBoxLayout()
        self.ca_edit = QLineEdit(tls_group)
        self.ca_edit.setText(self.record.tls_ca_bundle_path or "")
        ca_layout.addWidget(self.ca_edit)

        browse_btn = QPushButton("Browse…", tls_group)
        browse_btn.clicked.connect(self._browse_ca)
        ca_layout.addWidget(browse_btn)
        tls_layout.addRow("CA Bundle:", ca_layout)

        self.insecure_cb = QCheckBox(
            "Disable SSL/TLS certificate verification (Insecure)", tls_group
        )
        self.insecure_cb.setChecked(self.record.tls_insecure)
        tls_layout.addRow("", self.insecure_cb)

        form.addRow(tls_group)
        layout.addLayout(form)

        # Status Label
        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #d20f39; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save Changes", self)
        self.save_btn.setStyleSheet("font-weight: bold;")
        self.save_btn.clicked.connect(self._save_changes)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def _toggle_token_visibility(self) -> None:
        if self.token_edit.echoMode() == QLineEdit.Password:
            self.token_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.token_edit.setEchoMode(QLineEdit.Password)

    def _browse_ca(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CA Certificate Bundle",
            "",
            "Certificate Files (*.pem *.crt *.ca-bundle);;All Files (*)",
        )
        if file_path:
            self.ca_edit.setText(file_path)

    def _save_changes(self) -> None:
        label = self.label_edit.text().strip()
        username = self.username_edit.text().strip() or None
        new_token = self.token_edit.text().strip()
        ca_bundle = self.ca_edit.text().strip() or None
        insecure = self.insecure_cb.isChecked()

        if not label:
            self.status_label.setText("Error: Label cannot be empty.")
            return

        if new_token:
            # Validate new token in background first
            self.save_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.status_label.setStyleSheet("color: palette(text); font-size: 11px;")
            self.status_label.setText("Validating new token…")

            run_in_background(
                fn=lambda: _validate_credentials_probe(
                    self.record.provider,
                    self.record.instance_url,
                    new_token,
                    username,
                    ca_bundle,
                    insecure,
                ),
                on_finished=lambda _: self._apply_update(
                    label, username, new_token, ca_bundle, insecure
                ),
                on_failed=self._on_validation_failure,
            )
        else:
            self._apply_update(label, username, None, ca_bundle, insecure)

    def _apply_update(
        self,
        label: str,
        username: str | None,
        new_token: str | None,
        ca_bundle: str | None,
        insecure: bool,
    ) -> None:
        conn = db.get_connection()
        try:
            forge_accounts.update_account(
                conn,
                self.record.id,
                label=label,
                username=username,
                tls_ca_bundle_path=ca_bundle,
                tls_insecure=insecure,
            )
            if new_token:
                sec_key = forge_accounts.get_account_secret_key(conn, self.record.id)
                if sec_key:
                    credentials.get_backend().store_secret(
                        sec_key, new_token, label=f"Wrench: {label}"
                    )
        except Exception as exc:
            self.save_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            self.status_label.setStyleSheet("color: #d20f39; font-size: 11px;")
            self.status_label.setText(f"Failed to update account: {exc}")
            return
        finally:
            conn.close()

        self.accept()

    def _on_validation_failure(self, exc: Exception) -> None:
        self.save_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.status_label.setStyleSheet("color: #d20f39; font-size: 11px;")
        self.status_label.setText(f"Validation failed: {exc}")


class AccountsDialog(QDialog):
    """Management dialog listing all configured forge accounts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Forge Accounts")
        self.resize(650, 360)

        self._accounts: list[forge_accounts.ForgeAccountRecord] = []
        self._init_ui()
        self.reload_accounts()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Accounts table
        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Provider", "Instance URL", "Username", "Label", "TLS"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._edit_account)
        layout.addWidget(self.table, 1)

        # Button toolbar
        btn_bar = QHBoxLayout()
        self.add_btn = QPushButton("+ Add Account…", self)
        self.add_btn.setStyleSheet("font-weight: bold;")
        self.add_btn.clicked.connect(self._add_account)
        btn_bar.addWidget(self.add_btn)

        self.edit_btn = QPushButton("Edit…", self)
        self.edit_btn.clicked.connect(self._edit_account)
        btn_bar.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("Delete", self)
        self.delete_btn.setStyleSheet("color: #d20f39;")
        self.delete_btn.clicked.connect(self._delete_account)
        btn_bar.addWidget(self.delete_btn)

        btn_bar.addStretch()

        self.close_btn = QPushButton("Close", self)
        self.close_btn.clicked.connect(self.accept)
        btn_bar.addWidget(self.close_btn)

        layout.addLayout(btn_bar)

    def reload_accounts(self) -> None:
        conn = db.get_connection()
        try:
            self._accounts = forge_accounts.list_accounts(conn)
        finally:
            conn.close()

        self.table.setRowCount(len(self._accounts))
        for row, acc in enumerate(self._accounts):
            prov_item = QTableWidgetItem(acc.provider.capitalize())
            prov_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, prov_item)

            self.table.setItem(row, 1, QTableWidgetItem(acc.instance_url))
            self.table.setItem(row, 2, QTableWidgetItem(acc.username or "—"))
            self.table.setItem(row, 3, QTableWidgetItem(acc.label))

            tls_desc = "Standard"
            if acc.tls_insecure:
                tls_desc = "⚠️ Insecure"
            elif acc.tls_ca_bundle_path:
                tls_desc = "Custom CA"
            tls_item = QTableWidgetItem(tls_desc)
            tls_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, tls_item)

    def _get_selected_account(self) -> forge_accounts.ForgeAccountRecord | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._accounts):
            return self._accounts[row]
        return None

    def _add_account(self) -> None:
        dlg = AddAccountDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.reload_accounts()

    def _edit_account(self) -> None:
        acc = self._get_selected_account()
        if not acc:
            return
        dlg = EditAccountDialog(acc, self)
        if dlg.exec() == QDialog.Accepted:
            self.reload_accounts()

    def _delete_account(self) -> None:
        acc = self._get_selected_account()
        if not acc:
            return

        conn = db.get_connection()
        try:
            # Check if any repo links depend on this account
            linked_count = conn.execute(
                "SELECT COUNT(*) FROM repo_forge_links WHERE forge_account_id = ?",
                (acc.id,),
            ).fetchone()[0]
        finally:
            conn.close()

        warning_extra = ""
        if linked_count > 0:
            warning_extra = (
                f"\n\nWarning: {linked_count} repository link(s) use this account "
                f"and will also be removed."
            )

        reply = QMessageBox.question(
            self,
            "Delete Forge Account",
            f"Are you sure you want to delete '{acc.label}'?{warning_extra}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            conn = db.get_connection()
            try:
                forge_accounts.remove_account(conn, acc.id)
            finally:
                conn.close()
            self.reload_accounts()
