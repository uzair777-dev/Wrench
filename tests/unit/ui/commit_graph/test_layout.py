"""Unit tests for pure Python commit graph layout (layout.py, Phase 2)."""

from wrench.core.engine import Commit, LogFilter
from wrench.ui.commit_graph.layout import (
    ConnectorKind,
    compute_graph_layout,
    matches_filter,
)


def _make_commit(
    sha: str,
    parents: list[str],
    msg: str = "msg",
    author: str = "Alice",
    date: str = "2026-08-30T00:00:00Z",
) -> Commit:
    return Commit(
        sha=sha,
        message=msg,
        author_name=author,
        author_email=f"{author.lower()}@example.com",
        author_date=date,
        parent_shas=parents,
    )


class TestGraphLayout:
    def test_linear_history_single_lane(self):
        # 5 linear commits: c5 -> c4 -> c3 -> c2 -> c1
        commits = [
            _make_commit("c5", ["c4"]),
            _make_commit("c4", ["c3"]),
            _make_commit("c3", ["c2"]),
            _make_commit("c2", ["c1"]),
            _make_commit("c1", []),
        ]
        rows = compute_graph_layout(commits)
        assert len(rows) == 5
        for r in rows:
            assert r.lane_index == 0
            assert r.active_lanes == [0]
            assert r.connectors == []

    def test_branch_and_merge_fixture(self):
        # c4 (merge of c3 and c2) -> c3 (forked from c1), c2 (on main, parent c1) -> c1
        commits = [
            _make_commit("c4", ["c3", "c2"], msg="Merge feature"),
            _make_commit("c3", ["c1"], msg="Feature commit"),
            _make_commit("c2", ["c1"], msg="Main commit"),
            _make_commit("c1", [], msg="Initial commit"),
        ]
        rows = compute_graph_layout(commits)
        assert len(rows) == 4
        assert rows[0].lane_index == 0
        assert len(rows[0].connectors) == 1  # connector to secondary parent c2
        assert rows[0].connectors[0].to_lane == 0
        assert rows[0].connectors[0].kind == ConnectorKind.MERGE_UP

        # At c2 (in lane 1 connecting to parent c1 in lane 0), it emits a FORK_DOWN connector
        assert any(c.kind == ConnectorKind.FORK_DOWN for c in rows[2].connectors)

        # After merge, at c1 both lanes converge
        assert rows[3].lane_index == 0

    def test_octopus_merge_fixture(self):
        # Merge with 3 parents: c5 -> [c4, c3, c2]
        commits = [
            _make_commit("c5", ["c4", "c3", "c2"]),
            _make_commit("c4", ["c1"]),
            _make_commit("c3", ["c1"]),
            _make_commit("c2", ["c1"]),
            _make_commit("c1", []),
        ]
        rows = compute_graph_layout(commits)
        assert len(rows) == 5
        assert len(rows[0].connectors) == 2  # P2 and P3 connectors into lane 0

    def test_slot_recycling_prevents_lane_explosion(self):
        # 20 sequential branches that fork and merge back to main
        commits = []
        current_main = "root"
        commits.append(_make_commit("root", []))

        for i in range(15):
            feat = f"f_{i}"
            merge_sha = f"m_{i}"
            # Feature commit parent is current_main
            # Merge commit parents are [current_main, feat]
            commits.insert(0, _make_commit(feat, [current_main]))
            commits.insert(0, _make_commit(merge_sha, [current_main, feat]))
            current_main = merge_sha

        rows = compute_graph_layout(commits)
        max_lane = max(r.lane_index for r in rows)
        # Without slot recycling, 15 branches would use 15+ lanes. With recycling, max lane <= 3.
        assert max_lane <= 3

    def test_cross_batch_recompute_consistency(self):
        # 10 commits loaded all at once vs simulating scroll batches
        commits = [_make_commit(f"c{i}", [f"c{i - 1}"] if i > 0 else []) for i in range(10, 0, -1)]
        full_rows = compute_graph_layout(commits)
        partial_rows = compute_graph_layout(commits[:6])

        for i in range(6):
            assert full_rows[i].lane_index == partial_rows[i].lane_index
            assert full_rows[i].active_lanes == partial_rows[i].active_lanes

    def test_has_top_rail_and_color_persistence(self):
        # c3 (branch tip in lane 0) -> c2 (in lane 0) -> c1 (in lane 0)
        commits = [
            _make_commit("c3", ["c2"]),
            _make_commit("c2", ["c1"]),
            _make_commit("c1", []),
        ]
        rows = compute_graph_layout(commits)
        # Topmost commit has no child above it -> has_top_rail is False
        assert rows[0].has_top_rail is False
        # Intermediate commit was expected by c3 -> has_top_rail is True
        assert rows[1].has_top_rail is True
        assert rows[2].has_top_rail is True

        # Node color and active lane colors are populated
        assert rows[0].node_color == "#4C9EEB"
        assert len(rows[0].active_lane_colors) == 1
        assert rows[0].active_lane_colors[0] == (0, "#4C9EEB")


class TestMatchesFilter:

    def test_matches_author_and_message(self):
        c = _make_commit(
            "c1", [], msg="Fix login issue", author="Uzair", date="2026-08-30T10:00:00Z"
        )

        assert matches_filter(c, LogFilter(author="uzair")) is True
        assert matches_filter(c, LogFilter(author="bob")) is False

        assert matches_filter(c, LogFilter(message_substring="login")) is True
        assert matches_filter(c, LogFilter(message_substring="signup")) is False

        assert matches_filter(c, LogFilter(date_from="2026-08-30T09:00:00Z")) is True
        assert matches_filter(c, LogFilter(date_from="2026-08-30T11:00:00Z")) is False
