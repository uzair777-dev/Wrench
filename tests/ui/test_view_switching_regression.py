"""Regression tests for view switching, tab container lifecycle, and anti-ghosting."""

from unittest.mock import MagicMock

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from wrench.core.models import WorktreeInfo
from wrench.ui.tabs.tab_bar import _SINGLETON_TAB_TYPES, SafeStackedWidget, TabContainer
from wrench.ui.widgets.worktree_panel import SuppressTextDelegate, WorktreePanel


def test_safe_stacked_widget_suppresses_rogue_set_visible(qtbot):
    """SafeStackedWidget intercepts/suppresses rogue setVisible/show on inactive widgets."""
    stack = SafeStackedWidget()
    qtbot.addWidget(stack)

    w1 = QWidget()
    w2 = QWidget()
    stack.addWidget(w1)
    stack.addWidget(w2)

    stack.setCurrentWidget(w1)
    stack.show()

    assert stack.currentWidget() is w1
    assert w1.isVisible() is True
    assert w2.isVisible() is False

    # Attempt rogue show on inactive widget w2
    w2.setVisible(True)
    w2.show()

    # SafeStackedWidget event filter must suppress rogue visibility
    assert w2.isVisible() is False
    assert w1.isVisible() is True


def test_tab_container_pairwise_switching_mutual_exclusivity(qtbot):
    """Switching between tabs in TabContainer strictly hides all inactive widgets."""
    container = TabContainer(orientation=Qt.Orientation.Horizontal)
    qtbot.addWidget(container)

    widgets = [QWidget() for _ in range(4)]
    for i, w in enumerate(widgets):
        container.add_tab(
            widget=w,
            label=f"Tab {i}",
            tab_type="custom",
            closable=True,
            activate=(i == 0),
        )

    container.show()

    for active_idx in range(len(widgets)):
        container.set_current_index(active_idx)
        assert container.current_index() == active_idx
        assert widgets[active_idx].isVisible() is True

        for other_idx, other_w in enumerate(widgets):
            if other_idx != active_idx:
                assert (
                    other_w.isVisible() is False
                ), f"Widget {other_idx} was visible when Tab {active_idx} was active"


def test_worktree_panel_deferred_refresh_when_hidden(qtbot):
    """WorktreePanel defers refresh when hidden to avoid background git event ghosting."""
    engine = MagicMock()
    settings = MagicMock()
    settings.is_enabled.return_value = True

    parent = QWidget()
    qtbot.addWidget(parent)
    panel = WorktreePanel(engine, settings, parent=parent)
    panel.hide()

    panel.set_repo_path("/fake/repo")
    # Must remain hidden and defer refresh
    assert panel.isVisible() is False
    assert getattr(panel, "_needs_refresh", False) is True

    # Showing parent or activating tab triggers deferred refresh
    parent.show()
    panel.show()
    panel.tab_activated()
    assert getattr(panel, "_needs_refresh", False) is False


def test_worktree_tab_singleton_lifecycle(qtbot):
    """Worktree tabs are singletons so removal hides rather than deletes the widget."""
    assert "worktrees" in _SINGLETON_TAB_TYPES

    container = TabContainer(orientation=Qt.Orientation.Horizontal)
    qtbot.addWidget(container)

    wt_widget = QWidget()
    idx = container.add_tab(
        widget=wt_widget,
        label="Worktrees",
        tab_type="worktrees",
        closable=True,
        activate=True,
    )
    container.show()
    assert wt_widget.isVisible() is True

    container.remove_tab(idx)
    # Singleton widget must remain valid in memory and be hidden
    assert shiboken6.isValid(wt_widget) is True
    assert wt_widget.isVisible() is False


def test_worktree_card_delegate_suppresses_double_text(qtbot):
    """WorktreePanel installs SuppressTextDelegate to prevent double-text under cards."""
    engine = MagicMock()
    settings = MagicMock()
    settings.is_enabled.return_value = True

    panel = WorktreePanel(engine, settings)
    qtbot.addWidget(panel)

    delegate = panel.tree.itemDelegateForColumn(0)
    assert isinstance(delegate, SuppressTextDelegate)

    wt = WorktreeInfo(
        path="/tmp/fake-repo",
        head_oid="1111222233334444555566667777888899990000",
        branch_name="feature-test",
        is_bare=False,
        is_locked=False,
        lock_reason=None,
        is_prunable=False,
        is_main=False,
    )
    panel._repo_path = "/tmp/fake-repo"
    panel._worktrees = [wt]
    panel._rebuild_tree()

    # Item text must be preserved for accessibility and tests
    item = panel.tree.topLevelItem(0)
    assert item is not None
    assert "feature-test" in item.text(0)
