"""FR-5.6 / FR-8.1-8.5: Forge Accounts Management Dialogs."""

import logging
import threading
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
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
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench import credentials
from wrench.forge.capability import ForgeAdapter
from wrench.forge.exceptions import ForgeAuthenticationError, ForgeError
from wrench.forge.models import ForgeAccount
from wrench.forge.oauth.github_device_flow import (
    GITHUB_CLIENT_ID,
    DeviceFlowCodes,
    poll_for_token,
    request_device_code,
)
from wrench.forge.registry import get_adapter_class
from wrench.storage import db, forge_accounts
from wrench.ui.forge_panel.info_popover import InfoButton
from wrench.ui.workers import run_in_background

logger = logging.getLogger(__name__)

DEFAULT_URLS = {
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "bitbucket": "https://bitbucket.org",
    "forgejo": "https://codeberg.org",
}

PROVIDER_TOOLTIPS = {
    "github": {
        "token": (
            "<b>GitHub Personal Access Token</b><br><br>"
            "Generate one at:<br>"
            '<a href="https://github.com/settings/tokens?type=beta">'
            "Settings → Developer settings → Fine-grained tokens</a><br><br>"
            "<b>Required permissions:</b><br>"
            "• <code>repo</code> — full access (public + private)<br>"
            "• <code>workflow</code> — update GitHub Actions workflows<br>"
            "• <code>public_repo</code> — public repos only"
        ),
        "username": (
            "<b>GitHub Username</b><br><br>"
            "Optional. Wrench detects this automatically from your token.<br>"
            "You can find it at the top-right of github.com."
        ),
    },
    "gitlab": {
        "token": (
            "<b>GitLab Personal Access Token</b><br><br>"
            "Generate one at:<br>"
            '<a href="https://gitlab.com/-/user_settings/personal_access_tokens">'
            "Preferences → Access Tokens</a><br><br>"
            "<b>Required scopes:</b><br>"
            "• <code>api</code> — full access, OR<br>"
            "• <code>read_api</code> + <code>read_repository</code> — read-only"
        ),
        "username": (
            "<b>GitLab Username</b><br><br>"
            "Optional. Wrench detects this automatically from your token."
        ),
    },
    "forgejo": {
        "token": (
            "<b>Forgejo / Gitea API Token</b><br><br>"
            "Generate one at:<br>"
            "Settings → Applications → Manage Access Tokens<br><br>"
            "For Codeberg: "
            '<a href="https://codeberg.org/user/settings/applications">'
            "codeberg.org/user/settings/applications</a><br><br>"
            "<b>Select all needed scopes</b> (repo, issue, organization)."
        ),
        "username": (
            "<b>Forgejo / Gitea Username</b><br><br>"
            "Optional. Wrench detects this automatically from your token."
        ),
    },
    "bitbucket": {
        "token": (
            "<b>Bitbucket App Password</b><br><br>"
            "Generate one at:<br>"
            '<a href="https://bitbucket.org/account/settings/app-passwords/">'
            "Personal settings → App passwords</a><br><br>"
            "<b>Required permissions:</b><br>"
            "• Repositories: Read, Write<br>"
            "• Pull Requests: Read, Write<br>"
            "• Issues: Read"
        ),
        "username": (
            "<b>Atlassian Account Email (Required)</b><br><br>"
            "Bitbucket uses your Atlassian account email for authentication.<br>"
            "Find it at: "
            '<a href="https://id.atlassian.com/manage-profile/email">'
            "Atlassian account settings</a>"
        ),
    },
}

FIELD_TOOLTIPS = {
    "provider": (
        "<b>Forge Provider</b><br><br>"
        "The platform hosting your Git repositories.<br>"
        "Choose the service your remotes point to."
    ),
    "instance_url": (
        "<b>Instance URL</b><br><br>"
        "The base URL of your forge instance.<br><br>"
        "For cloud services, the default is correct.<br>"
        "For self-hosted instances (GitLab CE, Forgejo, etc.), "
        "enter your server URL:<br>"
        "<code>https://git.mycompany.com</code>"
    ),
    "label": (
        "<b>Account Label</b><br><br>"
        "A friendly name to identify this account in Wrench.<br>"
        "Examples: <em>Work GitHub</em>, <em>Personal GitLab</em><br><br>"
        "If left blank, Wrench generates one from your username."
    ),
    "ca_bundle": (
        "<b>CA Certificate Bundle</b><br><br>"
        "Path to a custom Certificate Authority bundle (<code>.pem</code> file).<br><br>"
        "Only needed if your self-hosted instance uses a "
        "private/corporate CA not in the system trust store."
    ),
    "insecure_tls": (
        "<b>⚠️ Disable TLS Verification</b><br><br>"
        "Skips <b>all</b> SSL/TLS certificate checking.<br>"
        "Only use for self-signed certificates in development.<br><br>"
        "<b>Never enable this for production instances.</b>"
    ),
}


def _make_label_widget(text: str, info_btn: InfoButton) -> QWidget:
    """Combine a label with an info button in a single widget for form layouts."""
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(QLabel(text))
    row.addWidget(info_btn)
    row.addStretch()
    return w


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
    """Modal dialog to add and validate a new forge account with assisted and manual modes."""

    def __init__(
        self,
        parent: QWidget | None = None,
        initial_page: int = 0,
        reauth_account_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "Re-authenticate GitHub Account" if reauth_account_id else "Add Forge Account"
        )
        self.setMinimumWidth(500)
        self._initial_page = initial_page
        self._reauth_account_id = reauth_account_id

        self._cancel_event = threading.Event()
        self._countdown_seconds = 0
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self._stack = QStackedWidget(self)
        self._chooser_page = self._create_chooser_page()
        self._assisted_page = self._create_assisted_page()
        self._manual_page = self._create_manual_page()

        self._stack.addWidget(self._chooser_page)
        self._stack.addWidget(self._assisted_page)
        self._stack.addWidget(self._manual_page)

        layout.addWidget(self._stack)
        self._stack.setCurrentIndex(self._initial_page)

    # --- Page 0: Method Chooser ---

    def _create_chooser_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setSpacing(14)

        title = QLabel("<h3>Add Forge Account</h3>", page)
        layout.addWidget(title)

        subtitle = QLabel("How would you like to set up your account?", page)
        subtitle.setStyleSheet("color: palette(mid); font-size: 13px;")
        layout.addWidget(subtitle)

        card_style = (
            "QPushButton { text-align: left; padding: 14px 16px; font-size: 13px; "
            "border: 1px solid palette(mid); border-radius: 8px; }"
            "QPushButton:hover { border-color: #1e66f5; "
            "background-color: rgba(30, 102, 245, 0.08); }"
        )

        self.assisted_btn = QPushButton(
            "🚀 Assisted Setup (GitHub)\n"
            "Sign in through your browser. Wrench handles the rest.\n"
            "Works with github.com and GitHub Enterprise Server.",
            page,
        )
        self.assisted_btn.setStyleSheet(card_style)
        self.assisted_btn.clicked.connect(lambda: self._stack.setCurrentIndex(1))
        layout.addWidget(self.assisted_btn)

        self.manual_btn = QPushButton(
            "🔧 Manual Setup\n"
            "Paste a Personal Access Token.\n"
            "Works with GitHub, GitLab, Forgejo, and Bitbucket.",
            page,
        )
        self.manual_btn.setStyleSheet(card_style)
        self.manual_btn.clicked.connect(lambda: self._stack.setCurrentIndex(2))
        layout.addWidget(self.manual_btn)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.chooser_cancel_btn = QPushButton("Cancel", page)
        self.chooser_cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.chooser_cancel_btn)
        layout.addLayout(btn_layout)

        return page

    # --- Page 1: Assisted Setup (Device Flow) ---

    def _create_assisted_page(self) -> QWidget:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setSpacing(12)

        # Top bar
        top_bar = QHBoxLayout()
        self.assisted_back_btn = QPushButton("← Back", page)
        self.assisted_back_btn.clicked.connect(self._on_assisted_back)
        top_bar.addWidget(self.assisted_back_btn)
        title_lbl = QLabel("<b>Assisted Setup (GitHub)</b>", page)
        title_lbl.setStyleSheet("font-size: 14px;")
        top_bar.addWidget(title_lbl)
        top_bar.addStretch()
        page_layout.addLayout(top_bar)

        # 1. Config form widget (initial state)
        self._assisted_form_widget = QWidget(page)
        form_layout = QVBoxLayout(self._assisted_form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)

        # Instance type
        type_group = QGroupBox("GitHub Instance", self._assisted_form_widget)
        type_layout = QVBoxLayout(type_group)
        self.instance_button_group = QButtonGroup(self)
        self.personal_radio = QRadioButton(
            "github.com (Personal / Organization)", self._assisted_form_widget
        )
        self.personal_radio.setChecked(True)
        self.cloud_radio = self.personal_radio
        self.enterprise_radio = QRadioButton("GitHub Enterprise Server", self._assisted_form_widget)
        self.instance_button_group.addButton(self.personal_radio)
        self.instance_button_group.addButton(self.enterprise_radio)
        self.personal_radio.toggled.connect(self._on_instance_type_changed)
        self.enterprise_radio.toggled.connect(self._on_instance_type_changed)
        type_layout.addWidget(self.personal_radio)
        type_layout.addWidget(self.enterprise_radio)

        # Enterprise URL container
        self.assisted_url_container = QWidget(type_group)
        url_row = QHBoxLayout(self.assisted_url_container)
        url_row.setContentsMargins(0, 4, 0, 0)
        self.assisted_url_label = QLabel("Enterprise URL:", self.assisted_url_container)
        url_row.addWidget(self.assisted_url_label)
        self.assisted_url_edit = QLineEdit(self.assisted_url_container)
        self.assisted_url_edit.setPlaceholderText("https://github.yourcompany.com")
        url_row.addWidget(self.assisted_url_edit)
        self.assisted_url_info_btn = InfoButton(
            FIELD_TOOLTIPS["instance_url"], self.assisted_url_container
        )
        url_row.addWidget(self.assisted_url_info_btn)
        self.assisted_url_container.setVisible(False)
        self.assisted_url_edit.setVisible(False)
        type_layout.addWidget(self.assisted_url_container)

        form_layout.addWidget(type_group)

        # Scope chooser
        scope_group = QGroupBox("Permissions & Scope", self._assisted_form_widget)
        scope_layout = QVBoxLayout(scope_group)
        self.scope_button_group = QButtonGroup(self)

        self.full_scope_radio = QRadioButton(
            "Full Access (Recommended)", self._assisted_form_widget
        )
        self.full_scope_radio.setChecked(True)
        self.scope_button_group.addButton(self.full_scope_radio)
        scope_layout.addWidget(self.full_scope_radio)

        full_desc = QLabel(
            "Access public and private repositories, PRs, issues, CI status, "
            "and GitHub Actions workflows.",
            self._assisted_form_widget,
        )
        full_desc.setStyleSheet("color: palette(mid); font-size: 11px; margin-left: 20px;")
        scope_layout.addWidget(full_desc)

        sec_note = QLabel(
            "🔒 Your credentials never leave this device. Stored in your system's Secret Service.",
            self._assisted_form_widget,
        )
        sec_note.setStyleSheet(
            "color: #40a02b; font-size: 11px; margin-left: 20px; margin-bottom: 6px;"
        )
        scope_layout.addWidget(sec_note)

        self.public_scope_radio = QRadioButton(
            "Public Repositories Only", self._assisted_form_widget
        )
        self.scope_button_group.addButton(self.public_scope_radio)
        scope_layout.addWidget(self.public_scope_radio)

        public_desc = QLabel(
            "Only access public repositories. Private repos will not be visible.",
            self._assisted_form_widget,
        )
        public_desc.setStyleSheet("color: palette(mid); font-size: 11px; margin-left: 20px;")
        scope_layout.addWidget(public_desc)

        public_warn = QLabel(
            "⚠️ You won't be able to see or interact with private repositories.",
            self._assisted_form_widget,
        )
        public_warn.setStyleSheet("color: #df8e1d; font-size: 11px; margin-left: 20px;")
        scope_layout.addWidget(public_warn)

        form_layout.addWidget(scope_group)

        self.assisted_status_label = QLabel(self._assisted_form_widget)
        self.assisted_status_label.setWordWrap(True)
        form_layout.addWidget(self.assisted_status_label)

        form_layout.addStretch()

        form_btn_bar = QHBoxLayout()
        form_btn_bar.addStretch()
        self.assisted_connect_btn = QPushButton("Sign in with GitHub", self._assisted_form_widget)
        self.assisted_connect_btn.setStyleSheet("font-weight: bold; padding: 6px 16px;")
        self.assisted_connect_btn.clicked.connect(self._start_device_flow)
        form_btn_bar.addWidget(self.assisted_connect_btn)
        form_layout.addLayout(form_btn_bar)

        page_layout.addWidget(self._assisted_form_widget)

        # 2. Waiting sub-state widget (shown once device code request succeeds)
        self._assisted_waiting_widget = QWidget(page)
        wait_layout = QVBoxLayout(self._assisted_waiting_widget)
        wait_layout.setSpacing(12)

        wait_layout.addWidget(
            QLabel("1. Open this URL in your browser:", self._assisted_waiting_widget)
        )
        url_row2 = QHBoxLayout()
        self.verification_url_label = QLabel(self._assisted_waiting_widget)
        self.verification_url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.verification_url_label.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: #1e66f5;"
        )
        url_row2.addWidget(self.verification_url_label)
        self.open_browser_btn = QPushButton("Open in Browser", self._assisted_waiting_widget)
        self.open_browser_btn.clicked.connect(self._open_browser_url)
        url_row2.addWidget(self.open_browser_btn)
        self.copy_url_btn = QPushButton("Copy URL", self._assisted_waiting_widget)
        self.copy_url_btn.clicked.connect(self._copy_verification_url)
        url_row2.addWidget(self.copy_url_btn)
        wait_layout.addLayout(url_row2)

        wait_layout.addWidget(QLabel("2. Enter this code:", self._assisted_waiting_widget))
        code_row = QHBoxLayout()
        self.user_code_label = QLabel(self._assisted_waiting_widget)
        self.user_code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.user_code_label.setStyleSheet(
            "font-family: monospace; font-size: 22px; font-weight: bold; "
            "letter-spacing: 2px; padding: 8px; border: 1px dashed palette(mid); "
            "border-radius: 6px;"
        )
        self.user_code_label.setAlignment(Qt.AlignCenter)
        code_row.addWidget(self.user_code_label)
        self.copy_code_btn = QPushButton("Copy Code", self._assisted_waiting_widget)
        self.copy_code_btn.clicked.connect(self._copy_user_code)
        code_row.addWidget(self.copy_code_btn)
        wait_layout.addLayout(code_row)

        self.waiting_status_label = QLabel(
            "⏳ Waiting for authorization…", self._assisted_waiting_widget
        )
        self.waiting_status_label.setWordWrap(True)
        self.waiting_status_label.setStyleSheet("font-size: 12px;")
        wait_layout.addWidget(self.waiting_status_label)

        self.countdown_label = QLabel("Code expires in --:--", self._assisted_waiting_widget)
        self.countdown_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        wait_layout.addWidget(self.countdown_label)

        self.waiting_progress_bar = QProgressBar(self._assisted_waiting_widget)
        self.waiting_progress_bar.setRange(0, 0)
        wait_layout.addWidget(self.waiting_progress_bar)

        wait_layout.addStretch()

        wait_actions = QHBoxLayout()
        self.assisted_try_again_btn = QPushButton("Try Again", self._assisted_waiting_widget)
        self.assisted_try_again_btn.setVisible(False)
        self.assisted_try_again_btn.clicked.connect(self._on_try_again_clicked)
        wait_actions.addWidget(self.assisted_try_again_btn)

        self.assisted_manual_fallback_btn = QPushButton(
            "Use Manual Setup", self._assisted_waiting_widget
        )
        self.assisted_manual_fallback_btn.setVisible(False)
        self.assisted_manual_fallback_btn.clicked.connect(self._on_fallback_to_manual)
        wait_actions.addWidget(self.assisted_manual_fallback_btn)

        wait_actions.addStretch()

        self.waiting_cancel_btn = QPushButton("Cancel", self._assisted_waiting_widget)
        self.waiting_cancel_btn.clicked.connect(self._on_assisted_cancel)
        wait_actions.addWidget(self.waiting_cancel_btn)
        wait_layout.addLayout(wait_actions)

        self._assisted_waiting_widget.setVisible(False)
        page_layout.addWidget(self._assisted_waiting_widget)

        return page

    # --- Page 2: Manual Setup (Form Enhanced with InfoButtons) ---

    def _create_manual_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        # Top bar
        top_bar = QHBoxLayout()
        self.manual_back_btn = QPushButton("← Back", page)
        self.manual_back_btn.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        top_bar.addWidget(self.manual_back_btn)
        title_lbl = QLabel("<b>Manual Setup</b>", page)
        title_lbl.setStyleSheet("font-size: 14px;")
        top_bar.addWidget(title_lbl)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Provider
        self.provider_combo = QComboBox(page)
        self.provider_combo.addItem("GitHub", "github")
        self.provider_combo.addItem("GitLab", "gitlab")
        self.provider_combo.addItem("Forgejo / Gitea", "forgejo")
        self.provider_combo.addItem("Bitbucket Cloud", "bitbucket")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_info_btn = InfoButton(FIELD_TOOLTIPS["provider"], page)
        form.addRow(_make_label_widget("Provider:", self.provider_info_btn), self.provider_combo)

        # Instance URL
        self.url_edit = QLineEdit(page)
        self.url_edit.setText(DEFAULT_URLS["github"])
        self.url_info_btn = InfoButton(FIELD_TOOLTIPS["instance_url"], page)
        form.addRow(_make_label_widget("Instance URL:", self.url_info_btn), self.url_edit)

        # Label
        self.label_edit = QLineEdit(page)
        self.label_edit.setPlaceholderText("e.g. Work GitHub, Personal GitLab")
        self.label_info_btn = InfoButton(FIELD_TOOLTIPS["label"], page)
        form.addRow(_make_label_widget("Account Label:", self.label_info_btn), self.label_edit)

        # Username
        self.username_edit = QLineEdit(page)
        self.username_edit.setPlaceholderText("Optional (required for Bitbucket)")
        self.username_info_btn = InfoButton(PROVIDER_TOOLTIPS["github"]["username"], page)
        form.addRow(
            _make_label_widget("Username / Email:", self.username_info_btn), self.username_edit
        )

        # Token
        token_layout = QHBoxLayout()
        self.token_edit = QLineEdit(page)
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("Personal Access Token / App Password")
        token_layout.addWidget(self.token_edit)

        self.toggle_token_btn = QToolButton(page)
        self.toggle_token_btn.setText("👁")
        self.toggle_token_btn.setToolTip("Show / Hide Token")
        self.toggle_token_btn.clicked.connect(self._toggle_token_visibility)
        token_layout.addWidget(self.toggle_token_btn)
        self.token_info_btn = InfoButton(PROVIDER_TOOLTIPS["github"]["token"], page)
        form.addRow(_make_label_widget("Token / Secret:", self.token_info_btn), token_layout)

        # TLS / Advanced Group
        self.tls_group = QGroupBox("TLS & Enterprise Security", page)
        tls_layout = QFormLayout(self.tls_group)

        ca_layout = QHBoxLayout()
        self.ca_edit = QLineEdit(self.tls_group)
        self.ca_edit.setPlaceholderText("Optional path to custom CA bundle (.pem)")
        ca_layout.addWidget(self.ca_edit)

        browse_btn = QPushButton("Browse…", self.tls_group)
        browse_btn.clicked.connect(self._browse_ca)
        ca_layout.addWidget(browse_btn)
        self.ca_info_btn = InfoButton(FIELD_TOOLTIPS["ca_bundle"], self.tls_group)
        tls_layout.addRow(_make_label_widget("CA Bundle:", self.ca_info_btn), ca_layout)

        self.insecure_cb = QCheckBox(
            "Disable SSL/TLS certificate verification (Insecure)", self.tls_group
        )
        self.insecure_info_btn = InfoButton(FIELD_TOOLTIPS["insecure_tls"], self.tls_group)
        tls_layout.addRow(
            _make_label_widget("TLS Security:", self.insecure_info_btn), self.insecure_cb
        )

        form.addRow(self.tls_group)
        layout.addLayout(form)

        # Status / Error Label
        self.status_label = QLabel(page)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #d20f39; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel", page)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Validate & Save", page)
        self.save_btn.setStyleSheet("font-weight: bold;")
        self.save_btn.clicked.connect(self._validate_and_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

        return page

    # --- Assisted Setup Logic ---

    def _on_instance_type_changed(self) -> None:
        is_enterprise = self.enterprise_radio.isChecked()
        self.assisted_url_container.setVisible(is_enterprise)
        self.assisted_url_edit.setVisible(is_enterprise)

    def _start_device_flow(self) -> None:
        if self.enterprise_radio.isChecked():
            instance_url = self.assisted_url_edit.text().strip().rstrip("/")
            if not instance_url:
                self.assisted_status_label.setStyleSheet("color: #d20f39; font-size: 11px;")
                self.assisted_status_label.setText("Error: Instance URL cannot be empty.")
                return
        else:
            instance_url = "https://github.com"

        scope = "repo workflow" if self.full_scope_radio.isChecked() else "public_repo"
        self._cancel_event.clear()
        self.assisted_status_label.setText("")
        self._assisted_form_widget.setVisible(False)
        self._assisted_waiting_widget.setVisible(True)
        self.waiting_progress_bar.setVisible(True)
        self.waiting_status_label.setStyleSheet("font-size: 12px;")
        self.waiting_status_label.setText("Connecting to GitHub…")
        self.countdown_label.setVisible(False)
        self.assisted_try_again_btn.setVisible(False)
        self.assisted_manual_fallback_btn.setVisible(False)
        self.verification_url_label.setText("...")
        self.user_code_label.setText("...")

        run_in_background(
            fn=lambda: request_device_code(
                GITHUB_CLIENT_ID, scope=scope, instance_url=instance_url
            ),
            on_finished=lambda codes: self._on_device_codes_received(codes, instance_url),
            on_failed=self._on_device_flow_error,
        )

    def _on_device_codes_received(self, codes: DeviceFlowCodes, instance_url: str) -> None:
        if self._cancel_event.is_set():
            return
        self.verification_url_label.setText(codes.verification_uri)
        self.user_code_label.setText(codes.user_code)
        self.waiting_status_label.setStyleSheet("font-size: 12px;")
        self.waiting_status_label.setText("⏳ Waiting for authorization in browser…")
        self._countdown_seconds = codes.expires_in
        self.countdown_label.setVisible(True)
        mins = self._countdown_seconds // 60
        secs = self._countdown_seconds % 60
        self.countdown_label.setText(f"Code expires in {mins:02d}:{secs:02d}")
        self._countdown_timer.start()

        run_in_background(
            fn=lambda: poll_for_token(
                GITHUB_CLIENT_ID,
                codes.device_code,
                interval=codes.interval,
                expires_in=codes.expires_in,
                cancel_event=self._cancel_event,
                instance_url=instance_url,
            ),
            on_finished=lambda token: self._on_device_token_received(token, instance_url),
            on_failed=self._on_device_flow_error,
        )

    def _on_device_token_received(self, token: str, instance_url: str) -> None:
        self._countdown_timer.stop()
        self.waiting_status_label.setStyleSheet("font-size: 12px;")
        self.waiting_status_label.setText("Validating credentials…")

        run_in_background(
            fn=lambda: _validate_credentials_probe(
                "github", instance_url, token, None, None, False
            ),
            on_finished=lambda res: self._on_device_flow_save_success(
                instance_url, res.get("inferred_user"), token
            ),
            on_failed=self._on_device_flow_error,
        )

    def _on_device_flow_save_success(
        self, instance_url: str, username: str | None, token: str
    ) -> None:
        is_enterprise = "github.com" not in instance_url.lower()
        prefix = "GitHub Enterprise" if is_enterprise else "GitHub"
        user_suffix = f" ({username})" if username else ""
        label = f"{prefix}{user_suffix}"

        conn = db.get_connection()
        try:
            target_acc = None
            if self._reauth_account_id is not None:
                target_acc = forge_accounts.get_account_full(conn, self._reauth_account_id)

            if target_acc is None:
                accounts = forge_accounts.list_accounts(conn, provider="github")
                clean_url = instance_url.rstrip("/").lower()
                for acc in accounts:
                    if acc.instance_url.rstrip("/").lower() == clean_url:
                        if (
                            not username
                            or not acc.username
                            or acc.username.lower() == username.lower()
                        ):
                            target_acc = acc
                            break

            if target_acc:
                sec_key = forge_accounts.get_account_secret_key(conn, target_acc.id)
                if sec_key:
                    credentials.get_backend().store_secret(
                        sec_key, token, label=f"Wrench: {target_acc.label}"
                    )
                if username and not target_acc.username:
                    forge_accounts.update_username(conn, target_acc.id, username)
            else:
                forge_accounts.add_account(
                    conn,
                    provider="github",
                    instance_url=instance_url,
                    label=label,
                    username=username,
                    token=token,
                )
        except Exception as exc:
            self._on_device_flow_error(exc)
            return
        finally:
            conn.close()

        self.accept()

    def _on_device_flow_error(self, exc: Exception) -> None:
        """Map Device Flow errors to actionable UI messages."""
        self._countdown_timer.stop()
        self.waiting_progress_bar.setVisible(False)
        self.countdown_label.setVisible(False)

        msg = str(exc)
        show_manual_fallback = False
        show_try_again = True
        self.assisted_try_again_btn.setText("Try Again")

        if isinstance(exc, ForgeAuthenticationError):
            self.waiting_status_label.setStyleSheet(
                "color: #df8e1d; font-size: 12px; font-weight: bold;"
            )
            self.waiting_status_label.setText(
                "Authorization was denied. You can try again or use Manual Setup."
            )
            show_manual_fallback = True
        elif "expired" in msg.lower():
            self.waiting_status_label.setStyleSheet(
                "color: #df8e1d; font-size: 12px; font-weight: bold;"
            )
            self.waiting_status_label.setText(
                "The authorization code has expired (15 minute limit). "
                "Click below to generate a new code."
            )
            self.assisted_try_again_btn.setText("Get New Code")
        elif "cancelled" in msg.lower():
            self._reset_assisted_page()
            self._stack.setCurrentIndex(0)
            return
        elif "unauthorized_client" in msg.lower() or "could not be verified" in msg.lower():
            self.waiting_status_label.setStyleSheet(
                "color: #d20f39; font-size: 12px; font-weight: bold;"
            )
            self.waiting_status_label.setText(
                "The Wrench OAuth app could not be verified. "
                "This may be a temporary GitHub issue. "
                "Try Manual Setup instead."
            )
            show_manual_fallback = True
            show_try_again = False
        elif "unsupported_grant_type" in msg.lower() or "not enabled" in msg.lower():
            self.waiting_status_label.setStyleSheet(
                "color: #d20f39; font-size: 12px; font-weight: bold;"
            )
            self.waiting_status_label.setText(
                "Device Flow is not enabled for this GitHub instance. "
                "Your admin may need to enable it. "
                "Use Manual Setup instead."
            )
            show_manual_fallback = True
            show_try_again = False
        elif "ssl" in msg.lower() or "certificate" in msg.lower():
            self.waiting_status_label.setStyleSheet(
                "color: #d20f39; font-size: 12px; font-weight: bold;"
            )
            self.waiting_status_label.setText(
                "SSL certificate verification failed. "
                "If this is a self-hosted instance with a private CA, "
                "use Manual Setup to configure a custom CA bundle."
            )
            show_manual_fallback = True
        elif "status.github.com" in msg.lower() or "50" in msg:
            self.waiting_status_label.setStyleSheet(
                "color: #d20f39; font-size: 12px; font-weight: bold;"
            )
            self.waiting_status_label.setText(
                "GitHub is experiencing issues. " "Check status.github.com and try again later."
            )
        else:
            self.waiting_status_label.setStyleSheet(
                "color: #d20f39; font-size: 12px; font-weight: bold;"
            )
            self.waiting_status_label.setText(msg)

        self.assisted_try_again_btn.setVisible(show_try_again)
        self.assisted_manual_fallback_btn.setVisible(show_manual_fallback)

    def _on_countdown_tick(self) -> None:
        self._countdown_seconds = max(0, self._countdown_seconds - 1)
        mins = self._countdown_seconds // 60
        secs = self._countdown_seconds % 60
        self.countdown_label.setText(f"Code expires in {mins:02d}:{secs:02d}")
        if self._countdown_seconds <= 0:
            self._countdown_timer.stop()
            self._on_device_flow_error(
                ForgeError("The authorization code has expired. Please try again.")
            )

    def _open_browser_url(self) -> None:
        url_str = self.verification_url_label.text().strip()
        if url_str and url_str != "...":
            QDesktopServices.openUrl(QUrl(url_str))

    def _copy_verification_url(self) -> None:
        url_str = self.verification_url_label.text().strip()
        if url_str and url_str != "...":
            QGuiApplication.clipboard().setText(url_str)

    def _copy_user_code(self) -> None:
        code_str = self.user_code_label.text().strip()
        if code_str and code_str != "...":
            QGuiApplication.clipboard().setText(code_str)

    def _reset_assisted_page(self) -> None:
        self._cancel_event.set()
        self._countdown_timer.stop()
        self._assisted_waiting_widget.setVisible(False)
        self._assisted_form_widget.setVisible(True)
        self.assisted_status_label.setText("")

    def _on_assisted_back(self) -> None:
        self._reset_assisted_page()
        self._stack.setCurrentIndex(0)

    def _on_assisted_cancel(self) -> None:
        self._reset_assisted_page()
        self._stack.setCurrentIndex(0)

    def _on_fallback_to_manual(self) -> None:
        self._reset_assisted_page()
        self._stack.setCurrentIndex(2)

    def _on_try_again_clicked(self) -> None:
        self._reset_assisted_page()
        self._start_device_flow()

    def reject(self) -> None:
        self._cancel_event.set()
        self._countdown_timer.stop()
        super().reject()

    # --- Manual Setup Logic ---

    def _on_provider_changed(self) -> None:
        prov = self.provider_combo.currentData()
        self.url_edit.setText(DEFAULT_URLS.get(prov, "https://"))
        if prov == "bitbucket":
            self.username_edit.setPlaceholderText("Atlassian Account Email (Required)")
        else:
            self.username_edit.setPlaceholderText("Optional (inferred from token)")

        p_info = PROVIDER_TOOLTIPS.get(prov, {})
        if "username" in p_info:
            self.username_info_btn.set_tooltip_html(p_info["username"])
        if "token" in p_info:
            self.token_info_btn.set_tooltip_html(p_info["token"])

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

        if self.record.provider == "github":
            reauth_layout = QHBoxLayout()
            self.reauth_btn = QPushButton("🚀 Re-authorize with GitHub (Browser)…", self)
            self.reauth_btn.clicked.connect(self._reauth_github)
            reauth_layout.addWidget(self.reauth_btn)
            reauth_layout.addStretch()
            form.addRow("Re-authorize:", reauth_layout)

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

    def _reauth_github(self) -> None:
        dlg = AddAccountDialog(self, initial_page=1, reauth_account_id=self.record.id)
        if "github.com" not in self.record.instance_url.lower():
            dlg.enterprise_radio.setChecked(True)
            dlg.assisted_url_edit.setText(self.record.instance_url)
        else:
            dlg.personal_radio.setChecked(True)
        if dlg.exec() == QDialog.Accepted:
            self.accept()


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

        self.reauth_btn = QPushButton("Re-authorize…", self)
        self.reauth_btn.clicked.connect(self._reauth_account)
        btn_bar.addWidget(self.reauth_btn)

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

    def _reauth_account(self) -> None:
        acc = self._get_selected_account()
        if not acc:
            return
        if acc.provider == "github":
            dlg = AddAccountDialog(self, initial_page=1, reauth_account_id=acc.id)
            if "github.com" not in acc.instance_url.lower():
                dlg.enterprise_radio.setChecked(True)
                dlg.assisted_url_edit.setText(acc.instance_url)
            else:
                dlg.personal_radio.setChecked(True)
            if dlg.exec() == QDialog.Accepted:
                self.reload_accounts()
        else:
            self._edit_account()

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
