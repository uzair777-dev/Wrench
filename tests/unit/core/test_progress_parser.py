"""Tests for the extended _parse_progress regex table."""

from wrench.core.write_ops import _parse_progress


class TestParseProgress:
    """Progress-type matrix verification (Phase 4.6 step 1)."""

    # ── Existing rows (regression: must not change) ──────────────────
    def test_receiving_objects_percentage(self):
        result = _parse_progress("Receiving objects:  42% (100/238)")
        assert result == (42, "Receiving objects")

    def test_remote_prefix_stripped(self):
        result = _parse_progress("remote: Counting objects:  10% (5/50)")
        assert result == (10, "Counting objects")

    def test_resolving_deltas(self):
        result = _parse_progress("Resolving deltas: 100% (20/20)")
        assert result == (100, "Resolving deltas")

    def test_noise_returns_none(self):
        assert _parse_progress("From github.com:user/repo") is None
        assert _parse_progress("   * branch main -> FETCH_HEAD") is None
        assert _parse_progress("") is None

    # ── New rows (Phase 4.6 additions) ───────────────────────────────
    def test_rebase_fraction(self):
        result = _parse_progress("Rebasing (3/10)")
        assert result == (30, "Rebasing")

    def test_rebase_single(self):
        result = _parse_progress("Rebasing (1/1)")
        assert result == (100, "Rebasing")

    def test_lfs_fraction(self):
        result = _parse_progress("Git LFS: (5 of 20 files)")
        assert result == (25, "Git LFS")

    def test_lfs_single_file(self):
        result = _parse_progress("Git LFS: (1 of 1 file)")
        assert result == (100, "Git LFS")

    def test_lfs_noise_no_match(self):
        # LFS lines without the "(N of M" pattern should not match
        assert _parse_progress("Git LFS: endpoint=https://...") is None

    def test_compressing_objects(self):
        result = _parse_progress("Compressing objects:  75% (3/4)")
        assert result == (75, "Compressing objects")
