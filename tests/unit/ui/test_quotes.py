"""Tests for the centralized humor/quotes bank module."""

import pytest

from wrench.ui.quotes import (
    ABOUT_WISDOM,
    CLEAN_STATE_QUOTES,
    EMPTY_ISSUES_LINES,
    EMPTY_PR_LINES,
    EMPTY_REPO_LINES,
    IDLE_LINES,
    MILESTONE_LINES,
    SUCCESS_LINES,
    WAITING_LINES,
    random_quote,
)


class TestQuoteBanks:
    """Each bank must be non-empty and every line <= 120 chars."""

    @pytest.mark.parametrize(
        "bank_name,bank",
        [
            ("CLEAN_STATE_QUOTES", CLEAN_STATE_QUOTES),
            ("WAITING_LINES", WAITING_LINES),
            ("SUCCESS_LINES", SUCCESS_LINES),
            ("EMPTY_REPO_LINES", EMPTY_REPO_LINES),
            ("EMPTY_PR_LINES", EMPTY_PR_LINES),
            ("EMPTY_ISSUES_LINES", EMPTY_ISSUES_LINES),
            ("IDLE_LINES", IDLE_LINES),
            ("ABOUT_WISDOM", ABOUT_WISDOM),
        ],
    )
    def test_bank_is_nonempty(self, bank_name, bank):
        assert len(bank) > 0, f"{bank_name} must not be empty"

    @pytest.mark.parametrize(
        "bank_name,bank",
        [
            ("CLEAN_STATE_QUOTES", CLEAN_STATE_QUOTES),
            ("WAITING_LINES", WAITING_LINES),
            ("SUCCESS_LINES", SUCCESS_LINES),
            ("EMPTY_REPO_LINES", EMPTY_REPO_LINES),
            ("EMPTY_PR_LINES", EMPTY_PR_LINES),
            ("EMPTY_ISSUES_LINES", EMPTY_ISSUES_LINES),
            ("IDLE_LINES", IDLE_LINES),
            ("ABOUT_WISDOM", ABOUT_WISDOM),
        ],
    )
    def test_bank_lines_max_120_chars(self, bank_name, bank):
        for i, entry in enumerate(bank):
            # CLEAN_STATE_QUOTES are (quote, author) tuples
            text = entry[0] if isinstance(entry, tuple) else entry
            assert len(text) <= 120, f"{bank_name}[{i}] is {len(text)} chars: {text[:60]}..."

    def test_milestone_lines_are_keyed(self):
        """MILESTONE_LINES must be a dict of str -> str."""
        assert isinstance(MILESTONE_LINES, dict)
        assert len(MILESTONE_LINES) > 0
        for key, line in MILESTONE_LINES.items():
            assert isinstance(key, str)
            assert isinstance(line, str)
            assert len(line) <= 120

    def test_random_quote_returns_from_bank(self):
        bank = ["line a", "line b", "line c"]
        result = random_quote(bank)
        assert result in bank

    def test_clean_state_quotes_include_originals(self):
        """The transplanted bank must include the original 7 programming quotes."""
        quote_texts = [q[0] for q in CLEAN_STATE_QUOTES]
        authors = [q[1] for q in CLEAN_STATE_QUOTES]
        assert any("Simplicity" in q for q in quote_texts)
        assert any("Linus Torvalds" in a for a in authors)
