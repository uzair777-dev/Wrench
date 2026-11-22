#!/usr/bin/env python3
"""Auto-generate dev/REPO_MAP.md and dev/REPO_MAP_CORE.md from src/wrench/ using Python AST.

Provides an exact, zero-hallucination public symbol, dataclass field, Qt Signal,
and SettingsRegistry key index for fast coding models (Gemini Flash, etc.).
"""

from __future__ import annotations

import ast
import subprocess
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "wrench"
FULL_OUT_PATH = REPO_ROOT / "dev" / "REPO_MAP.md"
CORE_OUT_PATH = REPO_ROOT / "dev" / "REPO_MAP_CORE.md"

QT_BOILERPLATE_METHODS = frozenset(
    {
        "paintEvent",
        "resizeEvent",
        "mousePressEvent",
        "mouseMoveEvent",
        "mouseReleaseEvent",
        "mouseDoubleClickEvent",
        "wheelEvent",
        "keyPressEvent",
        "keyReleaseEvent",
        "enterEvent",
        "leaveEvent",
        "closeEvent",
        "changeEvent",
        "showEvent",
        "hideEvent",
        "focusInEvent",
        "focusOutEvent",
        "contextMenuEvent",
        "eventFilter",
        "sizeHint",
        "minimumSizeHint",
        "paint",
        "createEditor",
        "setEditorData",
        "setModelData",
        "flags",
        "data",
        "rowCount",
        "columnCount",
        "headerData",
        "index",
        "parent",
    }
)


def _git_head_sha() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def _fmt_arg(arg: ast.arg, default: ast.expr | None = None) -> str:
    out = arg.arg
    if arg.annotation is not None:
        out += f": {ast.unparse(arg.annotation)}"
    if default is not None:
        out += f" = {ast.unparse(default)}"
    return out


def _fmt_signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    a = fn.args
    parts: list[str] = []
    pos_all = list(a.posonlyargs) + list(a.args)
    def_offset = len(pos_all) - len(a.defaults)
    for idx, arg in enumerate(pos_all):
        default = a.defaults[idx - def_offset] if idx >= def_offset else None
        parts.append(_fmt_arg(arg, default))
        if a.posonlyargs and idx == len(a.posonlyargs) - 1:
            parts.append("/")
    if a.vararg:
        parts.append("*" + _fmt_arg(a.vararg))
    elif a.kwonlyargs:
        parts.append("*")
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        parts.append(_fmt_arg(arg, default))
    if a.kwarg:
        parts.append("**" + _fmt_arg(a.kwarg))
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns is not None else ""
    prefix = "async " if isinstance(fn, ast.AsyncFunctionDef) else ""
    return f"{prefix}{fn.name}({', '.join(parts)}){ret}"


def _is_dataclass(cls: ast.ClassDef) -> bool:
    return any("dataclass" in ast.unparse(dec) for dec in cls.decorator_list)


def _extract_settings_keys(registry_path: Path) -> dict[str, list[tuple[str, str]]]:
    by_cat: dict[str, list[tuple[str, str]]] = defaultdict(list)
    if not registry_path.exists():
        return by_cat
    tree = ast.parse(registry_path.read_text(encoding="utf-8"), filename=str(registry_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn_name = ast.unparse(node.func)
            if fn_name.endswith("SettingSpec"):
                kw = {k.arg: ast.unparse(k.value) for k in node.keywords if k.arg}
                key = kw.get("key", "").strip("\"'")
                cat = kw.get("category", "Uncategorized").strip("\"'")
                default = kw.get("default", "?")
                if key:
                    by_cat[cat].append((key, default))
    return by_cat


def _summarize_module(py_file: Path) -> list[str]:
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_file))
    lines_out: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            base_str = f"({bases})" if bases else ""
            tag = "@dataclass " if _is_dataclass(node) else ""
            lines_out.append(f"- `{tag}class {node.name}{base_str}` (L{node.lineno})")

            fields: list[str] = []
            signals: list[str] = []
            methods: list[str] = []

            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fname = item.target.id
                    if not fname.startswith("_"):
                        ann = ast.unparse(item.annotation)
                        val = f" = {ast.unparse(item.value)}" if item.value is not None else ""
                        fields.append(f"{fname}: {ann}{val}")
                elif isinstance(item, ast.Assign):
                    val_src = ast.unparse(item.value)
                    if val_src.startswith("Signal("):
                        for tgt in item.targets:
                            if isinstance(tgt, ast.Name) and not tgt.id.startswith("_"):
                                signals.append(f"{tgt.id} = {val_src}")
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name in QT_BOILERPLATE_METHODS:
                        continue
                    if item.name == "__init__" or not item.name.startswith("_"):
                        methods.append(_fmt_signature(item))

            if fields:
                lines_out.append(f"  - **Fields:** `{'; '.join(fields)}`")
            if signals:
                lines_out.append(f"  - **Signals:** `{'; '.join(signals)}`")
            for m_sig in methods:
                lines_out.append(f"  - `{m_sig}`")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                lines_out.append(f"- `def {_fmt_signature(node)}` (L{node.lineno})")

    return lines_out


def _is_core_module(rel: Path) -> bool:
    rel_s = rel.as_posix()
    if any(
        rel_s.startswith(pfx)
        for pfx in (
            "src/wrench/core/",
            "src/wrench/storage/",
            "src/wrench/forge/",
            "src/wrench/watcher/",
            "src/wrench/credentials/",
        )
    ):
        return True
    return rel_s in (
        "src/wrench/ui/main_window.py",
        "src/wrench/ui/theme.py",
        "src/wrench/ui/icons.py",
        "src/wrench/ui/workers.py",
    )


def _write_map(
    out_path: Path,
    title: str,
    head_sha: str,
    settings_by_cat: dict[str, list[tuple[str, str]]],
    modules: list[tuple[Path, int, list[str]]],
) -> None:
    out: list[str] = [
        f"# {title}",
        "",
        f"> Generated from `src/wrench/` at git HEAD `{head_sha}` by",
        "> `scripts/generate_repo_map.py`. Treat every dataclass field, `Signal`,",
        "> `SettingsRegistry` key, and signature below as live ground truth.",
        "",
        "---",
        "",
        "## 1. Registered `SettingsRegistry` Keys (Do Not Duplicate)",
        "",
    ]
    for cat in sorted(settings_by_cat):
        entries = ", ".join(f"`{k}` (`{d}`)" for k, d in settings_by_cat[cat])
        out.append(f"- **{cat}:** {entries}")

    out.extend(["", "---", "", "## 2. Public Modules, Dataclasses, Signals & Signatures", ""])
    for rel, line_count, summary in modules:
        out.append(f"### `{rel}` ({line_count} lines)")
        out.extend(summary)
        out.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "\n".join(out).rstrip() + "\n"
    out_path.write_text(rendered, encoding="utf-8")
    est_tokens = len(rendered) // 4
    print(
        f"✔ Generated {out_path.relative_to(REPO_ROOT)} "
        f"({len(modules)} modules, {len(out)} lines, ~{est_tokens:,} est. tokens)"
    )


def main() -> None:
    head_sha = _git_head_sha()
    py_files = sorted(SRC_ROOT.rglob("*.py"))
    settings_by_cat = _extract_settings_keys(SRC_ROOT / "storage" / "settings_registry.py")

    all_modules: list[tuple[Path, int, list[str]]] = []
    core_modules: list[tuple[Path, int, list[str]]] = []

    for py_file in py_files:
        rel = py_file.relative_to(REPO_ROOT)
        summary = _summarize_module(py_file)
        if not summary:
            continue
        line_count = len(py_file.read_text(encoding="utf-8").splitlines())
        entry = (rel, line_count, summary)
        all_modules.append(entry)
        if _is_core_module(rel):
            core_modules.append(entry)

    _write_map(
        FULL_OUT_PATH,
        "Wrench Auto-Generated Full Repository Symbol Map (`dev/REPO_MAP.md`)",
        head_sha,
        settings_by_cat,
        all_modules,
    )
    _write_map(
        CORE_OUT_PATH,
        "Wrench Auto-Generated Core API Symbol Map (`dev/REPO_MAP_CORE.md`)",
        head_sha,
        settings_by_cat,
        core_modules,
    )


if __name__ == "__main__":
    main()
