"""Reusable UI widgets for Wrench."""

from wrench.ui.widgets.avatar import (
    AvatarLoader,
    AvatarWidget,
    get_avatar_loader,
    get_gravatar_url,
    render_initials_tile,
)
from wrench.ui.widgets.branch_switcher import BranchSwitcherWidget
from wrench.ui.widgets.loading_overlay import SpinnerWidget, TabLoadingOverlay

__all__ = [
    "AvatarLoader",
    "AvatarWidget",
    "BranchSwitcherWidget",
    "SpinnerWidget",
    "TabLoadingOverlay",
    "get_avatar_loader",
    "get_gravatar_url",
    "render_initials_tile",
]
