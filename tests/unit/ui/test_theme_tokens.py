"""FR-13.2 Gate Test: Assert zero hardcoded hex color literals outside theme.py."""

import re
from pathlib import Path

HEX_PATTERN = re.compile(r"#[0-9a-fA-F]{3}\b|#[0-9a-fA-F]{6}\b")


def test_no_hardcoded_hex_colors_outside_theme():
    """Scans all Python files in src/wrench/ui and asserts no hex literals exist
    outside of theme.py.
    """
    ui_dir = Path("src/wrench/ui")
    assert ui_dir.is_dir(), f"UI directory not found at {ui_dir.resolve()}"

    violations = []

    for file_path in ui_dir.rglob("*.py"):
        if file_path.name == "theme.py":
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            violations.append(f"Error reading {file_path}: {exc}")
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            # Exclude comments
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            matches = HEX_PATTERN.findall(line)
            if matches:
                violations.append(
                    f"{file_path}:{line_no}: Found hardcoded hex {matches} in line: {line.strip()}"
                )

    assert (
        not violations
    ), f"Found {len(violations)} hardcoded hex color literal(s) outside theme.py:\n" + "\n".join(
        violations[:50]
    )
