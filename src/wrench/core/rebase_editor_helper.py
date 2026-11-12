"""Standalone GIT_SEQUENCE_EDITOR / GIT_EDITOR helper for interactive rebase (VP-2).

Invoked by Git via:
    python -m wrench.core.rebase_editor_helper <plan_json_path> <git_target_path>
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_DONE_CMD_RE = re.compile(r"^(?:reword|r|squash|s)\s+([0-9a-fA-F]{4,64})\b")


def _load_plan(plan_path: Path) -> dict[str, Any]:
    raw = plan_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Interactive rebase plan must be a JSON object")
    return data


def _save_plan(plan_path: Path, plan: dict[str, Any]) -> None:
    payload = json.dumps(plan, indent=2)
    tmp_path = plan_path.with_suffix(".json.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, plan_path)
    os.chmod(plan_path, 0o600)


def _sanitize_summary(summary: str) -> str:
    return " ".join(summary.replace("\r", " ").replace("\n", " ").split())


def apply_sequence_plan(todo_path: Path, plan: dict[str, Any]) -> None:
    """Rewrite git-rebase-todo cleanly according to the planned entries."""
    entries = plan.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Interactive rebase plan contains no entries")

    lines: list[str] = []
    for item in entries:
        action = str(item.get("action", "")).strip()
        oid = str(item.get("oid", "")).strip()
        summary = _sanitize_summary(str(item.get("summary", "")))
        if not action or not oid:
            raise ValueError(f"Invalid interactive rebase entry: {item!r}")
        if summary:
            lines.append(f"{action} {oid} {summary}\n")
        else:
            lines.append(f"{action} {oid}\n")

    todo_path.write_text("".join(lines), encoding="utf-8")


def _active_oid_from_done(plan: dict[str, Any]) -> str | None:
    git_dir_str = plan.get("git_dir")
    if not git_dir_str:
        return None
    done_path = Path(str(git_dir_str)) / "rebase-merge" / "done"
    if not done_path.is_file():
        return None
    try:
        lines = done_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _DONE_CMD_RE.match(stripped)
        if match:
            return match.group(1)
        return None
    return None


def _lookup_message_by_oid(messages_by_oid: dict[str, str], active_oid: str) -> str | None:
    if active_oid in messages_by_oid:
        return messages_by_oid[active_oid]
    lower_active = active_oid.lower()
    for full_oid, msg in messages_by_oid.items():
        lower_full = full_oid.lower()
        if lower_full.startswith(lower_active) or lower_active.startswith(lower_full):
            return msg
    return None


def apply_commit_message(msg_path: Path, plan_path: Path, plan: dict[str, Any]) -> None:
    """Apply a user-supplied custom commit message when reword/squash triggers GIT_EDITOR."""
    messages_by_oid = plan.get("messages_by_oid")
    active_oid = _active_oid_from_done(plan)
    new_message: str | None = None
    matched_by_done = False

    if active_oid and isinstance(messages_by_oid, dict):
        matched_by_done = True
        new_message = _lookup_message_by_oid(messages_by_oid, active_oid)

    # Consume slot if fallback needed (or keep slot queue aligned even when matched via done)
    slots = plan.get("pending_message_slots")
    if isinstance(slots, list) and slots:
        fallback_msg = slots.pop(0)
        plan["pending_message_slots"] = slots
        _save_plan(plan_path, plan)
        if not matched_by_done:
            new_message = fallback_msg

    if new_message is not None:
        normalized = str(new_message).rstrip("\r\n")
        if normalized.strip():
            msg_path.write_text(normalized + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint called by Git for GIT_SEQUENCE_EDITOR and GIT_EDITOR."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("Usage: python -m wrench.core.rebase_editor_helper <plan_json> <target>\n")
        return 2

    plan_path = Path(args[0])
    target_path = Path(args[1])

    try:
        plan = _load_plan(plan_path)
        name = target_path.name
        if name == "git-rebase-todo" or name.endswith("-todo"):
            apply_sequence_plan(target_path, plan)
        else:
            apply_commit_message(target_path, plan_path, plan)
    except Exception as exc:
        sys.stderr.write(f"wrench.core.rebase_editor_helper error: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
