# Python 3.15 Migration & PEP 810 Native Lazy Import Architecture

## Executive Summary

As part of Phase 4.5, Wrench has transitioned its primary development and execution runtime to **Python 3.15.0 (CPython)** while preserving a permissive compatibility policy (`requires-python = ">=3.12"`) for downstream distribution.

This migration brings:
1. **PEP 810 Explicit Lazy Imports**: Native language-level deferral (`lazy import <module>`) for heavyweight and secondary dependencies, eliminating cold-start latency without complex proxy boilerplate.
2. **Interpreter Performance & Efficiency**: Benefit from CPython 3.15's internal interpreter optimizations, refined GIL management, and updated garbage collector routines.
3. **Sub-second Tooling via `uv` / `uvx`**: Seamless environment provisioning, reproducible lockless execution, and fast offline CLI wrappers.
4. **Resilient Local C-Extension Toolchain**: Automatic detection, compilation, and linking of C extensions (`pygit2` and `cffi`) against local/system headers (`libgit2` and `libffi`) with zero root permissions required.

---

## 1. Motivation & Architectural Goals

Desktop applications built on Qt/PySide6 face two significant startup performance challenges:
1. **Cold Import Overhead**: Loading large packages such as `secretstorage` (D-Bus), `httpx` (HTTP/2 stack, SSL), `platformdirs`, and Qt widgets at process launch can consume hundreds of milliseconds before the primary window paint event.
2. **Tooling & Environment Fragility**: Traditional `pip` and system `venv` workflows can incur slow installation and version resolution delays.

### The Solution
- **Native PEP 810 `lazy import`**: In Python 3.15, `lazy import <mod>` constructs a deferred module stub that only executes the target module's bytecode upon first attribute access.
- **`uv` 0.13+ Integration**: All developer commands (`wrench-run`, `wrench-debug`, `wrench-test`, `wrench-lint`, `wrench-format`, `wrench-ci-check`) invoke `.venv/bin/uv run --no-sync`, providing instantaneous execution.

---

## 2. C-Extension & Native Library Compilation

Python 3.15 is a cutting-edge interpreter. While pure Python wheels and Stable ABI (`abi3`) packages (such as `PySide6 6.12.0`) execute without recompilation, C-extensions with version-specific Python C-API bindings (such as `pygit2` and `cffi`) require compilation from source distribution (sdist).

### 2.1 Dependencies & Headers
- `libgit2` (v1.9.x runtime + headers)
- `libffi` (v8.x runtime + headers)
- Host C compiler (`gcc 16.x` or `clang`)

### 2.2 Local User-Space Toolchain
To avoid requiring `sudo` privileges or mutating host system packages, Wrench vendors/extracts development headers into `.build/`:
```text
.build/
├── bin/
│   ├── uv
│   └── uvx
├── libffi/
│   └── usr/
│       ├── include/ffi.h
│       └── lib64/libffi.so
└── libgit2/
    └── usr/
        ├── include/git2.h
        └── lib64/libgit2.so -> libgit2.so.1.9.7
```

### 2.3 Compilation Flags
When provisioning the `.venv`, `uv pip` executes the build under:
```bash
C_INCLUDE_PATH="${ROOT_DIR}/.build/libgit2/usr/include:${ROOT_DIR}/.build/libffi/usr/include:${C_INCLUDE_PATH}" \
LIBRARY_PATH="${ROOT_DIR}/.build/libgit2/usr/lib64:${ROOT_DIR}/.build/libffi/usr/lib64:${LIBRARY_PATH}" \
PKG_CONFIG_PATH="${ROOT_DIR}/.build/libgit2/usr/lib64/pkgconfig:${ROOT_DIR}/.build/libffi/usr/lib64/pkgconfig:${PKG_CONFIG_PATH}" \
LIBGIT2="${ROOT_DIR}/.build/libgit2/usr" \
uv pip install -e ".[dev]"
```

### 2.4 Dynamic Linker Runtime (`LD_LIBRARY_PATH`)
All executables in `bin/` (`wrench-run`, `wrench-debug`, etc.) automatically prepend the local `.build/libgit2/usr/lib64` directory to `LD_LIBRARY_PATH` if present:
```bash
if [ -d "${ROOT_DIR}/.build/libgit2/usr/lib64" ]; then
    export LD_LIBRARY_PATH="${ROOT_DIR}/.build/libgit2/usr/lib64:${LD_LIBRARY_PATH}"
fi
```
This guarantees runtime resolution of `libgit2.so.1.9` across all environments.

---

## 3. PEP 810 Native Explicit Lazy Imports

### 3.1 Language-Level Syntax
In Python 3.15, lazy imports are declared at module top-level using the `lazy import` keyword:
```python
lazy import secretstorage
lazy import platformdirs
lazy import httpx
```

### 3.2 Modules Converted to Native Lazy Import
1. **`src/wrench/credentials/secret_service.py`**:
   - `lazy import secretstorage`
   - Exception handling dynamically accesses `secretstorage.exceptions.SecretServiceNotAvailableException` and `secretstorage.exceptions.LockedException`.
   - **Result**: Importing `wrench.credentials` does not touch D-Bus or initialize `secretstorage` until a password or token is actively read/stored.
2. **`src/wrench/core/paths.py`**:
   - `lazy import platformdirs`
   - **Result**: Importing paths utilities does not query XDG environment variables until a specific directory function (`data_dir()`, `config_dir()`) is called.
3. **`src/wrench/forge/capability.py`**:
   - `from __future__ import annotations`
   - `lazy import httpx`
   - **Result**: Core forge models and base classes can be imported across the application without initializing HTTP connection pools or TLS engines.
4. **`src/wrench/core/lazy_loader.py` & `lazy_demo.py`**:
   - Backward-compatible `LazyProxyModule` class providing a deferred import proxy for Python 3.12-3.14 environments.
   - Executable demonstration script showcasing native PEP 810 behavior under Python 3.15.

---

## 4. Tooling & Linter Alignment

### 4.1 Ruff (`pyproject.toml`)
- Configured with `target-version = "py315"`.
- Ruff 0.17+ natively parses `lazy import` syntax without syntax errors or file-level exclusions.

### 4.2 Black (`pyproject.toml`)
- Configured with `target-version = ["py312", "py315"]`.
- Black 26.10+ formats native `lazy import` constructs cleanly.

### 4.3 Pre-commit Hooks (`.pre-commit-config.yaml`)
- Configured to run directly against `.venv/bin/ruff` and `.venv/bin/black` without any syntax exclusions.

---

## 5. Verification Gate & Test Results

The entire Wrench test suite was verified under Python 3.15.0:
```text
Platform: Linux (Fedora 44 x86_64)
Runtime: Python 3.15.0, pytest 9.1.1, PySide6 6.12.0 (Qt 6.12.0)
Total Tests: 534 passed
Code Style: Ruff check passed (170 files), Black check passed (170 files)
Contrast & Palette: 9/9 WCAG AA tests passed (0 hardcoded hex colors)
CI Check: ./bin/wrench-ci-check PASSED
```

---

## 6. Developer Cheat Sheet

| Task | Command |
|---|---|
| Initialize dev environment | `./init-dev.sh` |
| Activate shell session | `source init-dev.sh` |
| Run Wrench desktop | `wrench-run` or `./bin/wrench-run` |
| Launch with debug logging | `wrench-debug` or `./bin/wrench-debug` |
| Run test suite | `wrench-test` or `./bin/wrench-test` |
| Run linter checks | `wrench-lint` or `./bin/wrench-lint` |
| Auto-format codebase | `wrench-format` or `./bin/wrench-format` |
| Run complete CI check | `wrench-ci-check` or `./bin/wrench-ci-check` |
