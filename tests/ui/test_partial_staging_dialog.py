"""UI tests for PartialStagingDialog."""

from PySide6.QtWidgets import QDialog

from wrench.ui.dialogs.partial_staging_dialog import (
    PartialStagingChoice,
    PartialStagingDialog,
)


def test_partial_staging_dialog_elements(qtbot) -> None:
    files = ["src/core.py", "src/ui.py"]
    dlg = PartialStagingDialog(files, commit_message="feat: test commit")
    qtbot.addWidget(dlg)

    assert dlg.file_list.count() == 2
    assert dlg.remember_cb.isChecked() is False
    assert dlg.stage_all_btn.isEnabled()
    assert dlg.staged_only_btn.isEnabled()
    assert dlg.cancel_btn.isEnabled()


def test_partial_staging_dialog_stage_all_choice(qtbot) -> None:
    dlg = PartialStagingDialog(["file.txt"])
    qtbot.addWidget(dlg)

    dlg.remember_cb.setChecked(True)
    dlg.stage_all_btn.click()

    assert dlg.choice == PartialStagingChoice.STAGE_ALL_AND_COMMIT
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_partial_staging_dialog_staged_only_choice(qtbot) -> None:
    dlg = PartialStagingDialog(["file.txt"])
    qtbot.addWidget(dlg)

    dlg.staged_only_btn.click()

    assert dlg.choice == PartialStagingChoice.COMMIT_STAGED_ONLY
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_partial_staging_dialog_cancel_choice(qtbot) -> None:
    dlg = PartialStagingDialog(["file.txt"])
    qtbot.addWidget(dlg)

    dlg.cancel_btn.click()

    assert dlg.choice == PartialStagingChoice.CANCEL
    assert dlg.result() == QDialog.DialogCode.Rejected


def test_partial_staging_dialog_prompt_default_override() -> None:
    choice, remember = PartialStagingDialog.prompt(
        parent=None,
        file_paths=["file.txt"],
        default_choice=PartialStagingChoice.STAGE_ALL_AND_COMMIT,
    )
    assert choice == PartialStagingChoice.STAGE_ALL_AND_COMMIT
    assert remember is False
