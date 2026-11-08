"""Tests for BusyOperationDialog humor line behavior."""

from wrench.ui.recovery.busy_dialog import BusyOperationDialog


def test_humor_label_hidden_initially(qapp):
    dlg = BusyOperationDialog("Test", "Working...")
    dlg.show()
    assert not dlg.humor_label.isVisible()
    dlg.close()


def test_humor_label_hidden_when_determinate(qapp):
    dlg = BusyOperationDialog("Test", "Working...")
    dlg.show()
    dlg.set_progress(50)
    assert not dlg.humor_label.isVisible()
    assert not dlg._humor_timer.isActive()
    dlg.close()


def test_humor_timer_inactive_initially(qapp):
    dlg = BusyOperationDialog("Test", "Working...")
    dlg.show()
    assert not dlg._humor_timer.isActive()
    dlg.close()


def test_humor_disabled(qapp):
    dlg = BusyOperationDialog("Test", "Working...", humor_enabled=False)
    dlg.show()
    dlg.set_progress(0)
    assert not dlg._humor_start_timer.isActive()
    assert not dlg._humor_timer.isActive()
    dlg.close()


def test_humor_starts_after_delay(qapp, qtbot):
    dlg = BusyOperationDialog("Test", "Working...")
    dlg.show()
    dlg._humor_start_timer.setInterval(10)  # shorten for test
    dlg.set_progress(0)
    qtbot.wait(30)
    assert dlg.humor_label.isVisible()
    assert dlg.humor_label.text() != ""
    assert dlg._humor_timer.isActive()
    # Now set determinate progress - humor must immediately hide and stop
    dlg.set_progress(40)
    assert not dlg.humor_label.isVisible()
    assert not dlg._humor_timer.isActive()
    dlg.close()
