"""UI tests for push recovery dialogs (Secret Scanning, Protected Branch, File Too Large)."""

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from wrench.core.exceptions import (
    FileTooLargeRejectedError,
    ProtectedBranchRejectedError,
    SecretScanningRejectedError,
)
from wrench.ui.dialogs.push_recovery_dialogs import (
    FileTooLargeDialog,
    ProtectedBranchDialog,
    SecretScanningDialog,
)


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


class TestSecretScanningDialog:
    def test_renders_secret_type_and_location(self):
        exc = SecretScanningRejectedError(
            "Secret detected",
            secret_type="Stripe API Key",
            file_location="backend/billing.py:42",
            unblock_url="https://github.com/org/repo/security/secret-scanning/unblock-secret/xyz",
        )
        dlg = SecretScanningDialog(exc)
        assert "Stripe API Key" in dlg.secret_type_label.text()
        assert "backend/billing.py:42" in dlg.location_label.text()

    def test_unblock_button_opens_url(self):
        exc = SecretScanningRejectedError(
            "Secret detected",
            unblock_url="https://github.com/org/repo/security/secret-scanning/unblock-secret/xyz",
        )
        dlg = SecretScanningDialog(exc)
        with patch("PySide6.QtGui.QDesktopServices.openUrl") as mock_open:
            dlg.unblock_btn.click()
            mock_open.assert_called_once()

    def test_no_unblock_url_disables_button(self):
        exc = SecretScanningRejectedError("Secret detected")
        dlg = SecretScanningDialog(exc)
        assert not dlg.unblock_btn.isEnabled()


class TestProtectedBranchDialog:
    def test_renders_branch_name_and_reason(self):
        exc = ProtectedBranchRejectedError(
            "Protected branch update failed",
            branch_name="master",
            reason="Changes must be made through a pull request",
        )
        dlg = ProtectedBranchDialog(exc, default_new_branch="patch-1")
        assert dlg.branch_name_edit.text() == "patch-1"

    def test_get_new_branch_name(self):
        exc = ProtectedBranchRejectedError(
            "Protected branch update failed",
            branch_name="main",
        )
        dlg = ProtectedBranchDialog(exc, default_new_branch="fix/my-change")
        assert dlg.get_new_branch_name() == "fix/my-change"


class TestFileTooLargeDialog:
    def test_renders_filename_and_size(self):
        exc = FileTooLargeRejectedError(
            "File too large",
            filename="data/raw.parquet",
            filesize_mb=155.2,
            limit_mb=100.0,
        )
        dlg = FileTooLargeDialog(exc)
        assert "data/raw.parquet" in dlg.filename_label.text()
        assert "155.2" in dlg.filesize_label.text()
