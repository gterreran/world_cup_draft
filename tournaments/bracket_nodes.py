"""Bracket node utilities.

The tournament schedule stores bracket participants as source slots such as
``1A``, ``2D``, ``3CEFHI``, ``W49`` and ``L61``.  Those labels are useful because
we can read where a team *comes from*, but they are less convenient when we want
to simulate the bracket as a graph.

This module adds a lightweight graph layer without changing the database schema.
Each side of each knockout match becomes a concrete bracket node, for example:

``M049:H``
    Home side of match 49.

``M049:A``
    Away side of match 49.

The original schedule/source slot is preserved on the node, so callers can move
between human FIFA labels and concrete graph locations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
import re

from tournaments.models import Match, Tournament


BracketSide = Literal["home", "away"]
AdvancingOutcome = Literal["winner", "loser"]

DIRECT_SOURCE_SLOT_PATTERN = re.compile(r"^[12][A-L]$")
THIRD_PLACE_SOURCE_SLOT_PATTERN = re.compile(r"^3([A-L]+)$")
WINNER_SOURCE_SLOT_PATTERN = re.compile(r"^W(\d+)$")
LOSER_SOURCE_SLOT_PATTERN = re.compile(r"^L(\d+)$")

_SIDE_CODE = {
    "home": "H",
    "away": "A",
}

_STAGE_CODES = {
    Match.Stage.ROUND_OF_32: "R32",
    Match.Stage.ROUND_OF_16: "R16",
    Match.Stage.QUARTERFINAL: "QF",
    Match.Stage.SEMIFINAL: "SF",
    Match.Stage.THIRD_PLACE: "3P",
    Match.Stage.FINAL: "F",
}


@dataclass(frozen=True)
class BracketInputNode:
    """Concrete graph node representing one side of one knockout match."""

    node_id: str
    display_label: str
    match_number: int
    stage: str
    stage_code: str
    stage_index: int
    side: BracketSide
    side_code: str
    source_slot: str
    resolved_team_id: int | None = None

    @property
    def is_direct_group_slot(self) -> bool:
        return bool(DIRECT_SOURCE_SLOT_PATTERN.match(self.source_slot))

    @property
    def is_third_place_slot(self) -> bool:
        return bool(THIRD_PLACE_SOURCE_SLOT_PATTERN.match(self.source_slot))

    @property
    def source_groups(self) -> set[str]:
        """Return group letters compatible with this node's source slot."""

        if self.is_direct_group_slot:
            return {self.source_slot[1:]}

        third_match = THIRD_PLACE_SOURCE_SLOT_PATTERN.match(self.source_slot)
        if third_match:
            return set(third_match.group(1))

        return set()


@dataclass(frozen=True)
class BracketAdvanceEdge:
    """Directed graph edge from a completed match outcome into a later node."""

    from_match_number: int
    outcome: AdvancingOutcome
    to_node_id: str
    to_match_number: int
    to_side: BracketSide


@dataclass(frozen=True)
class BracketGraph:
    """Concrete graph representation of a tournament knockout bracket."""

    tournament: Tournament
    nodes: tuple[BracketInputNode, ...]
    edges: tuple[BracketAdvanceEdge, ...]
    match_numbers: tuple[int, ...]
    nodes_by_id: dict[str, BracketInputNode] = field(default_factory=dict)
    nodes_by_source_slot: dict[str, tuple[BracketInputNode, ...]] = field(default_factory=dict)
    direct_group_nodes: dict[str, BracketInputNode] = field(default_factory=dict)
    third_place_nodes_by_group: dict[str, tuple[BracketInputNode, ...]] = field(default_factory=dict)
    edges_by_match_number: dict[int, tuple[BracketAdvanceEdge, ...]] = field(default_factory=dict)

    def node_for_direct_slot(self, source_slot: str) -> BracketInputNode | None:
        """Return the concrete node for a direct source slot such as ``1A``."""

        return self.direct_group_nodes.get(source_slot.strip())

    def possible_nodes_for_third_group(self, group: str) -> tuple[BracketInputNode, ...]:
        """Return concrete nodes where a qualifying third-place group can land."""

        return self.third_place_nodes_by_group.get(group.strip().upper(), tuple())

    def nodes_for_source_slot(self, source_slot: str) -> tuple[BracketInputNode, ...]:
        """Return concrete nodes matching an exact source slot label."""

        return self.nodes_by_source_slot.get(source_slot.strip(), tuple())

    def outgoing_edges(self, match_number: int) -> tuple[BracketAdvanceEdge, ...]:
        """Return graph edges carrying winner/loser of a match to later nodes."""

        return self.edges_by_match_number.get(match_number, tuple())


def build_bracket_graph(tournament: Tournament) -> BracketGraph:
    """Build a concrete node graph from the tournament knockout schedule.

    No data is written to the database.  The graph is derived entirely from
    knockout ``Match`` rows and their ``home_slot`` / ``away_slot`` labels.
    """

    matches = list(
        Match.objects.filter(tournament=tournament)
        .exclude(stage=Match.Stage.GROUP)
        .select_related("home_team", "away_team")
        .order_by("match_date", "kickoff_time", "match_number", "id")
    )

    stage_counts: dict[str, int] = {}
    nodes: list[BracketInputNode] = []

    for match in matches:
        if match.match_number is None:
            continue

        stage_counts[match.stage] = stage_counts.get(match.stage, 0) + 1
        stage_index = stage_counts[match.stage]

        for side in ("home", "away"):
            source_slot = _source_slot(match, side)
            resolved_team_id = _resolved_team_id(match, side)
            node_id = bracket_node_id(match.match_number, side)
            stage_code = _stage_code(match.stage)
            side_code = _SIDE_CODE[side]

            nodes.append(
                BracketInputNode(
                    node_id=node_id,
                    display_label=f"{stage_code}-{stage_index:02d}-{side_code}",
                    match_number=match.match_number,
                    stage=match.stage,
                    stage_code=stage_code,
                    stage_index=stage_index,
                    side=side,
                    side_code=side_code,
                    source_slot=source_slot,
                    resolved_team_id=resolved_team_id,
                )
            )

    nodes_by_id = {node.node_id: node for node in nodes}
    nodes_by_source_slot = _index_nodes_by_source_slot(nodes)
    direct_group_nodes = _index_direct_group_nodes(nodes)
    third_place_nodes_by_group = _index_third_place_nodes_by_group(nodes)
    edges = _build_edges(nodes)
    edges_by_match_number = _index_edges_by_match_number(edges)

    return BracketGraph(
        tournament=tournament,
        nodes=tuple(nodes),
        edges=tuple(edges),
        match_numbers=tuple(
            match.match_number
            for match in matches
            if match.match_number is not None
        ),
        nodes_by_id=nodes_by_id,
        nodes_by_source_slot=nodes_by_source_slot,
        direct_group_nodes=direct_group_nodes,
        third_place_nodes_by_group=third_place_nodes_by_group,
        edges_by_match_number=edges_by_match_number,
    )


def bracket_node_id(match_number: int, side: BracketSide) -> str:
    """Return the canonical concrete node id for one side of a match."""

    return f"M{match_number:03d}:{_SIDE_CODE[side]}"


def _source_slot(match: Match, side: BracketSide) -> str:
    value = match.home_slot if side == "home" else match.away_slot
    return (value or "").strip()


def _resolved_team_id(match: Match, side: BracketSide) -> int | None:
    return match.home_team_id if side == "home" else match.away_team_id


def _stage_code(stage: str) -> str:
    return _STAGE_CODES.get(stage, stage.upper().replace("_", "-"))


def _index_nodes_by_source_slot(
    nodes: list[BracketInputNode],
) -> dict[str, tuple[BracketInputNode, ...]]:
    indexed: dict[str, list[BracketInputNode]] = {}

    for node in nodes:
        if not node.source_slot:
            continue
        indexed.setdefault(node.source_slot, []).append(node)

    return {slot: tuple(items) for slot, items in indexed.items()}


def _index_direct_group_nodes(
    nodes: list[BracketInputNode],
) -> dict[str, BracketInputNode]:
    indexed = {}

    for node in nodes:
        if node.is_direct_group_slot:
            indexed[node.source_slot] = node

    return indexed


def _index_third_place_nodes_by_group(
    nodes: list[BracketInputNode],
) -> dict[str, tuple[BracketInputNode, ...]]:
    indexed: dict[str, list[BracketInputNode]] = {}

    for node in nodes:
        third_match = THIRD_PLACE_SOURCE_SLOT_PATTERN.match(node.source_slot)
        if not third_match:
            continue

        for group in third_match.group(1):
            indexed.setdefault(group, []).append(node)

    return {group: tuple(items) for group, items in indexed.items()}


def _build_edges(nodes: list[BracketInputNode]) -> list[BracketAdvanceEdge]:
    edges = []

    for node in nodes:
        winner_match = WINNER_SOURCE_SLOT_PATTERN.match(node.source_slot)
        if winner_match:
            edges.append(
                BracketAdvanceEdge(
                    from_match_number=int(winner_match.group(1)),
                    outcome="winner",
                    to_node_id=node.node_id,
                    to_match_number=node.match_number,
                    to_side=node.side,
                )
            )
            continue

        loser_match = LOSER_SOURCE_SLOT_PATTERN.match(node.source_slot)
        if loser_match:
            edges.append(
                BracketAdvanceEdge(
                    from_match_number=int(loser_match.group(1)),
                    outcome="loser",
                    to_node_id=node.node_id,
                    to_match_number=node.match_number,
                    to_side=node.side,
                )
            )

    return edges


def _index_edges_by_match_number(
    edges: list[BracketAdvanceEdge],
) -> dict[int, tuple[BracketAdvanceEdge, ...]]:
    indexed: dict[int, list[BracketAdvanceEdge]] = {}

    for edge in edges:
        indexed.setdefault(edge.from_match_number, []).append(edge)

    return {match_number: tuple(items) for match_number, items in indexed.items()}
