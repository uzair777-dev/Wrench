"""Centralized humor and personality text banks (Phase 4.6).

All text in this module is pure data — callers wrap individual strings
with self.tr() at the point of display. Translators have full freedom
to re-localize puns; a note says so in each bank's docstring.

Toggle: ui.humor_lines (default True). When False, no bank is queried
and no rotation timers fire. The toggle control lives on the Appearance
settings page.
"""

import random
from collections.abc import Sequence

# ── Clean-state quotes (Changes tab when working tree is clean) ──────────
# Includes the original 7 programming quotes transplanted from changes_tab.py.
# Translators: puns may be freely adapted to the target language.
CLEAN_STATE_QUOTES: list[tuple[str, str]] = [
    # Original 7 (transplanted from changes_tab.py PROGRAMMING_QUOTES)
    ("Simplicity is prerequisite for reliability.", "Edsger W. Dijkstra"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("Code is like humor. When you have to explain it, it's bad.", "Cory House"),
    ("Clean code always looks like it was written by someone who cares.", "Robert C. Martin"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("Deleted code is debugged code.", "Jeff Sickel"),
    # Extended bank
    ("Programs must be written for people to read.", "Hal Abelson"),
    ("The best code is no code at all.", "Jeff Atwood"),
    ("Perfection is achieved when there is nothing left to take away.", "Antoine de Saint-Exupéry"),
    ("Any fool can write code that a computer can understand.", "Martin Fowler"),
    (
        "Walking on water and developing software from a spec are easy — if both are frozen.",
        "Edward V. Berard",
    ),
    ("It works on my machine. — Every developer, at some point.", "Anonymous"),
    ("A clean working tree is a happy working tree.", "Wrench"),
    ("Nothing to commit — time for coffee.", "Wrench"),
    ("All clear. Your repository is tidy.", "Wrench"),
]

# ── Waiting lines (rotate every ~4s during indeterminate ops > 8s) ───────
# These appear as a *muted secondary line* UNDER the real git stage text.
# The real stage text (e.g. "Receiving objects: 42%") is always primary.
WAITING_LINES: list[str] = [
    "Warming up the git engine…",
    "Counting bytes the honest way…",
    "Negotiating with the remote…",
    "Patience is a virtue — and a merge strategy.",
    "Teaching bits to travel faster…",
    "Resolving the mysteries of the object graph…",
    "This is the part where git does git things.",
    "Crunching objects — no shortcuts, promise.",
    "Your code is in transit. We didn't lose it.",
    "The remote is thinking. Give it a moment.",
    "Compiling excuses — no wait, compressing objects.",
    "Almost there. Probably.",
    "If it's taking a while, it's a big repo. That's fine.",
]

# ── Success lines (one line in the activity log on clean finishes) ────────
SUCCESS_LINES: list[str] = [
    "Done — clean as a whistle.",
    "All good. That was smooth.",
    "Completed without drama. The best kind.",
    "Success. Your repository thanks you.",
    "Wrapped up nicely.",
    "Finished — zero surprises.",
    "That went well. As it should.",
]

# ── Empty-state lines (zero-item states for various surfaces) ────────────
EMPTY_REPO_LINES: list[str] = [
    "No repositories yet. Open or clone one to get started.",
    "Your workspace is empty. Add a repository and let's go.",
    "Nothing here yet — every great project starts with a clone.",
]

EMPTY_PR_LINES: list[str] = [
    "No pull requests found. Time to ship something?",
    "All quiet on the PR front.",
    "No open PRs. Either everything's merged or nothing's started.",
]

EMPTY_ISSUES_LINES: list[str] = [
    "No issues. That's either great news or nobody's looking.",
    "Issue tracker is empty. Enjoy the silence.",
    "Zero issues found. Suspiciously clean.",
]

# ── Idle quip (single-shot after 30 min inactivity with dirty tree) ──────
IDLE_LINES: list[str] = [
    "Still there? You've got uncommitted changes waiting.",
    "Your working tree misses you. It has changes to discuss.",
    "30 minutes of silence. Your diff is getting lonely.",
    "Friendly nudge: uncommitted work is sitting in the tree.",
]

# ── Milestone toasts (fire-once-ever per key) ────────────────────────────
# Keys match event hooks; values are the one-liner posted to the activity dock.
MILESTONE_LINES: dict[str, str] = {
    "first_pr_created": "🎉 Your first pull request from Wrench! Nice.",
    "snapshot_100th": "📸 100 snapshots taken. Your safety net is strong.",
    "push_after_recovery": "💪 Pushed successfully after a recovered failure. Resilient.",
}

# ── About dialog wisdom (rotating in the About window) ───────────────────
ABOUT_WISDOM: list[str] = [
    "Built for people who think in branches.",
    "Git is hard. Your tools shouldn't be.",
    "A GUI that respects the CLI underneath.",
    "Every commit tells a story. We help you read it.",
    "Open source, because your tools should be yours.",
    "No telemetry. No tracking. Just git.",
    "Made with care, tested with paranoia.",
]


def random_quote(bank: Sequence[str] | Sequence[tuple[str, str]]) -> str | tuple[str, str]:
    """Return a random entry from a bank. Type matches the bank's element type."""
    return random.choice(bank)
