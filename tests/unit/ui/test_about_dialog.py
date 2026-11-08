"""Tests for the About dialog (Phase 4.6 step 5)."""

from PySide6.QtCore import Qt

from wrench.ui.dialogs.about_dialog import AboutDialog


def test_about_dialog_shows_version(qapp):
    dlg = AboutDialog()
    assert dlg.version_label.text()  # non-empty
    assert "wrench" in dlg.windowTitle().lower() or "about" in dlg.windowTitle().lower()
    dlg.close()


def test_about_dialog_has_license_pane(qapp):
    dlg = AboutDialog()
    assert dlg.license_text.toPlainText()  # non-empty license text
    dlg.close()


def test_about_dialog_has_links(qapp):
    dlg = AboutDialog()
    assert dlg.links_row is not None
    dlg.close()


def test_about_dialog_wisdom_line(qapp):
    dlg = AboutDialog()
    assert dlg.wisdom_label.text()  # non-empty, from ABOUT_WISDOM bank
    dlg.close()


def test_about_dialog_escape_closes(qapp, qtbot):
    dlg = AboutDialog()
    dlg.show()
    qtbot.keyClick(dlg, Qt.Key.Key_Escape)
    assert not dlg.isVisible()
