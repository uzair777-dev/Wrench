"""Smart cleanup, auto-healing, and error recovery subsystem for Wrench."""

from .classifier import DiagnosticReport, ErrorCategory, diagnose_error
from .process_guard import GuardResult, acquire_repo_guard, inspect_locks, is_pid_alive
from .sweeper import sweep_debris
from .transaction import WorkspaceTransaction, workspace_transaction

__all__ = [
    "DiagnosticReport",
    "ErrorCategory",
    "GuardResult",
    "WorkspaceTransaction",
    "acquire_repo_guard",
    "diagnose_error",
    "inspect_locks",
    "is_pid_alive",
    "sweep_debris",
    "workspace_transaction",
]
