"""Tests for explicit lazy imports (PEP 810 compatibility and lazy loader)."""

import os
import subprocess
import sys
from pathlib import Path

from wrench.core.lazy_loader import LazyProxyModule, lazy_import


def test_lazy_loader_defers_import():
    # Target a standard library module not yet imported in this test if possible,
    # or verify proxy wraps and resolves
    target = "colorsys"
    sys.modules.pop(target, None)

    proxy = lazy_import(target)
    assert isinstance(proxy, LazyProxyModule)
    assert target not in sys.modules

    # Attribute access should resolve the module
    rgb = proxy.hsv_to_rgb(0.5, 0.5, 0.5)
    assert rgb == (0.25, 0.5, 0.5)
    assert target in sys.modules


def test_lazy_demo_under_python_315():
    """Verify that Python 3.15 native `lazy import` syntax functions properly."""
    py315_path = Path(".uv_python/cpython-3.15.0-linux-x86_64-gnu/bin/python3.15")
    if not py315_path.is_file():
        return

    repo_root = Path(__file__).resolve().parents[3]
    demo_script = repo_root / "src" / "wrench" / "core" / "lazy_demo.py"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")

    proc = subprocess.run(
        [str(py315_path.resolve()), str(demo_script.resolve())],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"Python 3.15 demo failed: {proc.stderr}"
    assert "Math result: 5.0" in proc.stdout
    assert '{"wrench": "lazy_import", "python": "3.15"}' in proc.stdout


def test_lazy_modules_declarations():
    """Verify that __lazy_modules__ declarations exist in target entry points."""
    from wrench import app
    from wrench.core import git_credential_helper

    assert hasattr(git_credential_helper, "__lazy_modules__")
    assert "secretstorage" in git_credential_helper.__lazy_modules__

    assert hasattr(app, "__lazy_modules__")
    assert "watchdog" in app.__lazy_modules__
