"""FR-2.2: Pure Python commit graph layout engine.

Computes branch lanes, connector paths, and visual row structures from
a list of commits without any Qt dependencies. Fully testable without a display server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from wrench.core.engine import Commit, LogFilter, RefLabel

GRAPH_COLORS = [
    "#4C9EEB",  # blue
    "#E55B5B",  # red
    "#50C878",  # green
    "#F5A623",  # orange
    "#9B59B6",  # purple
    "#1ABC9C",  # teal
    "#E67E22",  # amber
    "#3498DB",  # light blue
    "#E74C3C",  # crimson
    "#2ECC71",  # emerald
]


class ConnectorKind(str, Enum):
    """Directional flow of a branch connector in the commit DAG."""

    FORK_DOWN = "fork_down"  # Node at y_center curving down to parent at y_bottom
    MERGE_UP = "merge_up"  # Branch from y_bottom curving up into merge node at y_center
    JOIN_TOP = "join_top"  # Branch from y_top curving down into node at y_center


@dataclass
class Lane:
    expected_sha: str | None
    color: str
    index: int


@dataclass
class Connector:
    from_lane: int
    to_lane: int
    color: str
    kind: ConnectorKind = ConnectorKind.MERGE_UP


@dataclass
class GraphRow:
    commit: Commit
    lane_index: int
    active_lanes: list[int]
    active_lane_colors: list[tuple[int, str]] = field(default_factory=list)
    node_color: str = GRAPH_COLORS[0]
    has_top_rail: bool = False
    connectors: list[Connector] = field(default_factory=list)
    ref_labels: list[RefLabel] = field(default_factory=list)


def compute_graph_layout(
    commits: list[Commit],
    ref_labels: dict[str, list[RefLabel]] | None = None,
) -> list[GraphRow]:
    """Assign lanes and connectors for commits in topological walk order.

    Implements Rules R1–R5 with slot recycling to avoid unbounded lane index growth.
    """
    ref_map = ref_labels or {}
    lanes: list[Lane | None] = []
    color_counter = 0
    rows: list[GraphRow] = []

    def allocate_lane(sha: str) -> int:
        nonlocal color_counter
        color = GRAPH_COLORS[color_counter % len(GRAPH_COLORS)]
        color_counter += 1

        # Slot recycling: re-use first available None slot
        for idx, lane in enumerate(lanes):
            if lane is None:
                lanes[idx] = Lane(expected_sha=sha, color=color, index=idx)
                return idx

        idx = len(lanes)
        lanes.append(Lane(expected_sha=sha, color=color, index=idx))
        return idx

    for commit in commits:
        connectors: list[Connector] = []
        occupied_lane = -1

        # R1: Find all lanes expecting this commit
        matching_indices = [
            i
            for i, lane in enumerate(lanes)
            if lane is not None and lane.expected_sha == commit.sha
        ]

        has_top_rail = bool(matching_indices)

        if matching_indices:
            occupied_lane = matching_indices[0]
            # Close any duplicate lanes expecting the same SHA, emit connectors into occupied lane
            for dup_idx in matching_indices[1:]:
                dup_lane = lanes[dup_idx]
                if dup_lane is not None:
                    connectors.append(
                        Connector(
                            from_lane=dup_idx,
                            to_lane=occupied_lane,
                            color=dup_lane.color,
                            kind=ConnectorKind.JOIN_TOP,
                        )
                    )
                    lanes[dup_idx] = None
        else:
            # R2: New branch tip we've just met
            occupied_lane = allocate_lane(commit.sha)

        curr_lane = lanes[occupied_lane]
        curr_lane_color = curr_lane.color if curr_lane is not None else GRAPH_COLORS[0]

        # Record active lanes and exact colors for this row BEFORE processing parents for next rows
        active_lanes_for_row = [i for i, lane in enumerate(lanes) if lane is not None]
        active_lane_colors = [(i, lane.color) for i, lane in enumerate(lanes) if lane is not None]

        # R3: Process parents
        parents = commit.parent_shas
        if not parents:
            # R4: Root commit -> close lane after this row
            lanes[occupied_lane] = None
        else:
            # P1: first parent continues in this lane (if no other surviving lane expects it)
            p1 = parents[0]
            other_expecting_p1 = [
                i
                for i, lane in enumerate(lanes)
                if lane is not None and i != occupied_lane and lane.expected_sha == p1
            ]
            if other_expecting_p1:
                target_lane = other_expecting_p1[0]
                connectors.append(
                    Connector(
                        from_lane=occupied_lane,
                        to_lane=target_lane,
                        color=curr_lane_color,
                        kind=ConnectorKind.FORK_DOWN,
                    )
                )
                lanes[occupied_lane] = None
            else:
                if lanes[occupied_lane] is not None:
                    lanes[occupied_lane].expected_sha = p1

            # P2..Pn: secondary parents (merge commits)
            for pi in parents[1:]:
                other_expecting_pi = [
                    i
                    for i, lane in enumerate(lanes)
                    if lane is not None and lane.expected_sha == pi
                ]

                if other_expecting_pi:
                    target_lane = other_expecting_pi[0]
                    target_color = (
                        lanes[target_lane].color if lanes[target_lane] else curr_lane_color
                    )
                    connectors.append(
                        Connector(
                            from_lane=target_lane,
                            to_lane=occupied_lane,
                            color=target_color,
                            kind=ConnectorKind.MERGE_UP,
                        )
                    )
                else:
                    new_idx = allocate_lane(pi)
                    new_color = lanes[new_idx].color if lanes[new_idx] else curr_lane_color
                    connectors.append(
                        Connector(
                            from_lane=new_idx,
                            to_lane=occupied_lane,
                            color=new_color,
                            kind=ConnectorKind.MERGE_UP,
                        )
                    )

        rows.append(
            GraphRow(
                commit=commit,
                lane_index=occupied_lane,
                active_lanes=active_lanes_for_row,
                active_lane_colors=active_lane_colors,
                node_color=curr_lane_color,
                has_top_rail=has_top_rail,
                connectors=connectors,
                ref_labels=ref_map.get(commit.sha, []),
            )
        )

    return rows


def matches_filter(
    commit: Commit,
    log_filter: LogFilter | None,
    matching_shas: set[str] | None = None,
) -> bool:
    """Predicate for client-side search/filtering of commits."""
    if not log_filter:
        return True

    if matching_shas is not None and commit.sha not in matching_shas:
        return False

    if log_filter.author:
        author_query = log_filter.author.lower()
        if (
            author_query not in commit.author_name.lower()
            and author_query not in commit.author_email.lower()
        ):
            return False

    if log_filter.message_substring:
        if log_filter.message_substring.lower() not in commit.message.lower():
            return False

    if log_filter.date_from and commit.author_date < log_filter.date_from:
        return False

    if log_filter.date_to and commit.author_date > log_filter.date_to:
        return False

    return True
