import pytest
from PySide6.QtWidgets import QApplication

from wrench.core.exceptions import GitNetworkTransferError
from wrench.ui.dialogs.push_recovery_dialogs import GitNetworkRecoveryDialog


@pytest.fixture
def sample_network_error():
    return GitNetworkTransferError(
        ["git", "push", "origin", "main"],
        1,
        "error: RPC failed; HTTP 408 curl 22",
        kind="timeout_408",
        status_code=408,
        curl_code=22,
        payload_mb=105.75,
    )


def test_network_recovery_dialog_init(qapp: QApplication, sample_network_error):
    dlg = GitNetworkRecoveryDialog(
        sample_network_error,
        remote_url="https://github.com/user/repo.git",
        has_multiple_commits=True,
    )
    assert "Network" in dlg.windowTitle()
    assert "105.8 MB" in dlg.info_label.text()
    assert dlg.auto_heal_btn is not None
    assert dlg.switch_ssh_btn is not None
    assert dlg.switch_ssh_btn.isEnabled() is True
    assert dlg.get_ssh_url() == "git@github.com:user/repo.git"


def test_network_recovery_dialog_large_blobs_warning(qapp: QApplication, sample_network_error):
    blobs = [("models/weights.bin", 120.5)]
    dlg = GitNetworkRecoveryDialog(
        sample_network_error,
        unpushed_large_blobs=blobs,
    )
    assert dlg.large_blobs_label is not None
    assert "models/weights.bin" in dlg.large_blobs_label.text()
    assert "120.5 MB" in dlg.large_blobs_label.text()


def test_network_recovery_dialog_actions(qapp: QApplication, sample_network_error):
    dlg = GitNetworkRecoveryDialog(sample_network_error)
    # Simulate Auto-Heal click
    dlg._on_auto_heal()
    assert dlg.get_action() == "auto_heal"

    # Simulate buffer retry click
    dlg._on_retry_buffer()
    assert dlg.get_action() == "retry_config"
    cfg = dlg.get_config_overrides()
    assert cfg.get("http.postBuffer") == "524288000"

    # Simulate HTTP/1.1 retry click
    dlg._on_retry_http1()
    assert dlg.get_action() == "retry_config"
    cfg_http1 = dlg.get_config_overrides()
    assert cfg_http1.get("http.version") == "HTTP/1.1"

    # Simulate Extreme Compression retry click
    dlg._on_retry_extreme()
    assert dlg.get_action() == "retry_config"
    cfg_ext = dlg.get_config_overrides()
    assert cfg_ext.get("core.compression") == "9"
    assert cfg_ext.get("pack.compression") == "9"


def test_pre_push_large_files_dialog_over_100mb(qapp: QApplication):
    from wrench.ui.dialogs.push_recovery_dialogs import PrePushLargeFilesDialog

    blobs = [("huge.bin", 125.0), ("medium.dat", 60.0)]
    dlg = PrePushLargeFilesDialog(blobs, remote="origin", branch="main")
    assert "Critical" in dlg.windowTitle()
    assert "Exceeds 100 MB Limit" in dlg.files_label.text()

    # Test actions
    dlg._on_extreme()
    assert dlg.action == "extreme_compression"

    dlg._on_anyway()
    assert dlg.action == "standard"

    dlg._on_cancel()
    assert dlg.action == "cancel"


def test_pre_push_large_files_dialog_under_100mb(qapp: QApplication):
    from wrench.ui.dialogs.push_recovery_dialogs import PrePushLargeFilesDialog

    blobs = [("dataset.csv", 65.0)]
    dlg = PrePushLargeFilesDialog(blobs, remote="origin", branch="feature")
    assert "Warning" in dlg.windowTitle()
