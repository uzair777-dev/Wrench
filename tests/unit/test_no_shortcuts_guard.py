import ast
import pathlib

SRC_ROOT = pathlib.Path("src/wrench")
UI_ROOT = SRC_ROOT / "ui"
FORBIDDEN_UI_IMPORTS = {"pygit2", "subprocess", "sqlite3", "httpx"}
FORBIDDEN_UI_INTERNAL_MODULES = {
    "wrench.core.read_ops",
    "wrench.core.write_ops",
    "wrench.storage.db",
}


def _iter_py_files(root: pathlib.Path):
    for p in root.rglob("*.py"):
        yield p


def test_ui_layer_never_imports_backends_directly() -> None:
    """Enforces ARCHITECTURE.md §1.2 and Rule 5: UI never imports backends directly."""
    violations = []
    for py_file in UI_ROOT.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if root_mod in FORBIDDEN_UI_IMPORTS:
                        violations.append(f"{py_file}:{node.lineno} forbidden import {alias.name}")
                    if alias.name in FORBIDDEN_UI_INTERNAL_MODULES:
                        violations.append(f"{py_file}:{node.lineno} forbidden import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_mod = node.module.split(".")[0]
                if root_mod in FORBIDDEN_UI_IMPORTS:
                    violations.append(
                        f"{py_file}:{node.lineno} forbidden from-import {node.module}"
                    )
                if node.module in FORBIDDEN_UI_INTERNAL_MODULES:
                    violations.append(
                        f"{py_file}:{node.lineno} forbidden from-import {node.module}"
                    )
    assert not violations, "UI layer import violations detected:\n" + "\n".join(violations)


def test_no_shell_true_or_not_implemented_stubs() -> None:
    """Enforces SEC-1 and SEC-7: No shell=True in core/forge and no NotImplementedError stubs."""
    for py_file in SRC_ROOT.rglob("*.py"):
        if py_file == SRC_ROOT / "credentials" / "__init__.py":
            continue
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                if getattr(node.exc.func, "id", "") == "NotImplementedError":
                    raise AssertionError(
                        f"{py_file}:{node.lineno} contains NotImplementedError stub"
                    )
            if isinstance(node, ast.Call) and py_file.name != "custom_actions.py":
                for kw in node.keywords:
                    if (
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        raise AssertionError(f"{py_file}:{node.lineno} uses forbidden shell=True")


def test_no_fstring_sql_queries_in_storage() -> None:
    """Enforces SEC-5: SQLite execute() calls must never use JoinedStr (f-strings)."""
    for py_file in (SRC_ROOT / "storage").rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in (
                "execute",
                "executemany",
            ):
                if node.args and isinstance(node.args[0], ast.JoinedStr):
                    raise AssertionError(
                        f"{py_file}:{node.lineno} uses forbidden f-string in SQL execute()"
                    )


FORBIDDEN_FLASH_PATTERNS = (
    ("from PyQt5", "PyQt5 hallucination — use PySide6"),
    ("from PyQt6", "PyQt6 hallucination — use PySide6"),
    ("import PyQt5", "PyQt5 hallucination — use PySide6"),
    ("import PyQt6", "PyQt6 hallucination — use PySide6"),
    ("pyqtSignal", "PyQt signal hallucination — use PySide6.QtCore.Signal"),
    ("pyqtSlot", "PyQt slot hallucination — use PySide6.QtCore.Slot"),
    (".exec_()", "Deprecated Qt5 .exec_() — use .exec() in Qt6"),
    (".iter_commits(", "GitPython hallucination — use pygit2 repo.walk()"),
    (".active_branch", "GitPython hallucination — use pygit2 repo.head.shorthand"),
    ("# ... existing", "Truncated file rewrite comment — keep all existing code intact"),
    ("# ... rest of", "Truncated file rewrite comment — keep all existing code intact"),
    ("# existing code", "Truncated file rewrite comment — keep all existing code intact"),
)


def test_no_flash_api_hallucinations_or_truncation_markers() -> None:
    """FLASH-1..FLASH-3: Reject PyQt5/PyQt6/GitPython hallucinations and truncated-file comments."""
    violations = []
    for py_file in _iter_py_files(SRC_ROOT):
        content = py_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(content.splitlines(), start=1):
            for bad_token, reason in FORBIDDEN_FLASH_PATTERNS:
                if bad_token in line:
                    violations.append(f"{py_file}:{lineno} [{reason}]: {line.strip()}")
            if "from PySide6.QtWidgets import" in line and "QAction" in line:
                violations.append(
                    f"{py_file}:{lineno} [QAction lives in PySide6.QtGui, not QtWidgets]"
                )
    assert not violations, "Flash model hallucination / truncation detected:\n" + "\n".join(
        violations
    )


def test_no_silent_exception_pass_in_src() -> None:
    """FLASH-5: Forbid silent `except Exception: pass` blocks that hide broken logic."""
    violations = []
    for py_file in _iter_py_files(SRC_ROOT):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    exc_name = getattr(node.type, "id", None) if node.type else "BaseException"
                    if exc_name in ("Exception", "BaseException"):
                        violations.append(
                            f"{py_file}:{node.lineno} silent `except {exc_name}: pass`"
                        )
    assert not violations, "Silent exception swallowing detected:\n" + "\n".join(violations)
