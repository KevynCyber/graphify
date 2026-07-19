"""Tests for scripts/graphify_inspect.py, a helper for ad-hoc graph.json inspection.

Replaces the previous pattern of hand-rolled `json.load` + dict-poking snippets
(retro finding 3c) with a small set of read-only query functions: summary stats,
node lookup, neighbor listing, community filtering, and relation queries. The
module works directly on an in-memory graph dict (NetworkX node-link JSON) so it
composes with graphs already loaded elsewhere, and also offers a `load_graph`
convenience that reads a graph.json off disk and normalizes the legacy "edges"
key to "links" (mirroring graphify.build's own edges/links tolerance).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# scripts/ is not a package (excluded from pytest's norecursedirs) and is not on
# sys.path; put the scripts dir itself on sys.path so graphify_inspect imports
# as a top-level module, mirroring tests/test_skillgen.py's REPO_ROOT insertion.
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import graphify_inspect  # noqa: E402


def _node(node_id, community, label=None):
    return {
        "id": node_id,
        "label": label or node_id,
        "file_type": "code",
        "source_file": f"{node_id.lower()}.py",
        "source_location": "1-10",
        "community": community,
        "norm_label": node_id.lower(),
    }


def _edge(source, target, relation, score=0.9):
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "confidence": "high",
        "confidence_score": score,
        "source_file": f"{source.lower()}.py",
        "source_location": "1",
        "weight": 1,
    }


def _small_graph(built_at_commit="deadbeef"):
    """4 nodes (A,B,C in communities 0/1/0, D isolated with community None),
    3 links across 2 relations (calls, imports), 1 hyperedge."""
    graph = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            _node("A", 0),
            _node("B", 1),
            _node("C", 0),
            _node("D", None),
        ],
        "links": [
            _edge("A", "B", "calls"),
            _edge("B", "C", "imports"),
            _edge("A", "C", "calls", score=0.8),
        ],
        "hyperedges": [
            {"id": "h1", "nodes": ["A", "B", "C"], "relation": "cluster"},
        ],
    }
    if built_at_commit is not None:
        graph["built_at_commit"] = built_at_commit
    return graph


def _empty_graph():
    return {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [],
        "links": [],
        "hyperedges": [],
    }


# Requirement: an agent inspecting graph.json needs a single summary call that
# reports node/edge/hyperedge/community counts and graph flags, instead of
# hand-rolling len() and set-comprehension snippets on the raw dict each time.
class TestSummary:
    def test_summary_counts_and_flags(self):
        graph = _small_graph()
        result = graphify_inspect.summary(graph)
        assert result == {
            "nodes": 4,
            "edges": 3,
            "hyperedges": 1,
            "communities": 2,
            "directed": True,
            "multigraph": False,
            "built_at_commit": "deadbeef",
        }

    def test_summary_built_at_commit_none_when_key_absent(self):
        graph = _small_graph(built_at_commit=None)
        assert "built_at_commit" not in graph
        result = graphify_inspect.summary(graph)
        assert result["built_at_commit"] is None

    def test_summary_on_empty_graph_is_all_zero(self):
        result = graphify_inspect.summary(_empty_graph())
        assert result == {
            "nodes": 0,
            "edges": 0,
            "hyperedges": 0,
            "communities": 0,
            "directed": True,
            "multigraph": False,
            "built_at_commit": None,
        }


# Requirement: an agent must be able to load a graph.json off disk without
# re-deriving the edges/links normalization graphify.build already does
# internally (NetworkX <= 3.1 serializes edges as "links"; some producers still
# emit "edges").
class TestLoadGraph:
    def test_load_graph_reads_json_file(self, tmp_path):
        graph = _small_graph()
        p = tmp_path / "graph.json"
        p.write_text(json.dumps(graph), encoding="utf-8")

        loaded = graphify_inspect.load_graph(p)

        assert graphify_inspect.summary(loaded) == graphify_inspect.summary(graph)
        assert graphify_inspect.get_node(loaded, "A") == _node("A", 0)

    def test_load_graph_normalizes_edges_key_to_links(self, tmp_path):
        graph = _small_graph()
        edges = graph.pop("links")
        graph["edges"] = edges
        p = tmp_path / "graph.json"
        p.write_text(json.dumps(graph), encoding="utf-8")

        loaded = graphify_inspect.load_graph(p)

        # downstream functions must see the edges as if they were under "links"
        assert graphify_inspect.summary(loaded)["edges"] == 3
        out = graphify_inspect.neighbors(loaded, "A")
        assert {n["neighbor"] for n in out} == {"B", "C"}


# Requirement: look up a single node's full attribute dict by id, without
# scanning the nodes list by hand each time.
class TestGetNode:
    def test_get_node_returns_full_attr_dict(self):
        graph = _small_graph()
        assert graphify_inspect.get_node(graph, "B") == _node("B", 1)

    def test_get_node_missing_id_returns_none(self):
        graph = _small_graph()
        assert graphify_inspect.get_node(graph, "does-not-exist") is None

    def test_get_node_on_empty_graph_returns_none(self):
        assert graphify_inspect.get_node(_empty_graph(), "A") is None


# Requirement: list a node's incident edges with direction, so an agent can
# trace both what a node depends on (out) and what depends on it (in) without
# re-deriving direction from source/target comparisons each time.
class TestNeighbors:
    def test_neighbors_includes_out_edges(self):
        graph = _small_graph()
        out = graphify_inspect.neighbors(graph, "A")
        assert {"neighbor": "B", "relation": "calls", "direction": "out"} in out
        assert {"neighbor": "C", "relation": "calls", "direction": "out"} in out
        assert len(out) == 2

    def test_neighbors_includes_in_edges(self):
        graph = _small_graph()
        out = graphify_inspect.neighbors(graph, "C")
        assert {"neighbor": "A", "relation": "calls", "direction": "in"} in out
        assert {"neighbor": "B", "relation": "imports", "direction": "in"} in out
        assert len(out) == 2

    def test_neighbors_mixed_in_and_out(self):
        graph = _small_graph()
        out = graphify_inspect.neighbors(graph, "B")
        assert {"neighbor": "A", "relation": "calls", "direction": "in"} in out
        assert {"neighbor": "C", "relation": "imports", "direction": "out"} in out
        assert len(out) == 2

    def test_neighbors_of_isolated_node_is_empty(self):
        graph = _small_graph()
        assert graphify_inspect.neighbors(graph, "D") == []

    def test_neighbors_on_empty_graph_is_empty(self):
        assert graphify_inspect.neighbors(_empty_graph(), "A") == []


# Requirement: filter nodes by community id, to inspect one detected cluster
# at a time instead of scanning the whole node list.
class TestNodesInCommunity:
    def test_nodes_in_community_filters_correctly(self):
        graph = _small_graph()
        result = graphify_inspect.nodes_in_community(graph, 0)
        assert result == [_node("A", 0), _node("C", 0)]

    def test_nodes_in_community_other_community(self):
        graph = _small_graph()
        result = graphify_inspect.nodes_in_community(graph, 1)
        assert result == [_node("B", 1)]

    def test_nodes_in_community_unused_id_returns_empty(self):
        graph = _small_graph()
        assert graphify_inspect.nodes_in_community(graph, 999) == []

    def test_nodes_in_community_on_empty_graph_returns_empty(self):
        assert graphify_inspect.nodes_in_community(_empty_graph(), 0) == []


# Requirement: query edges by relation type, and get an overall relation
# breakdown, to answer "what relations exist and how many of each" without
# hand-rolling a counter over the links list.
class TestEdgesByRelationAndHistogram:
    def test_edges_by_relation_filters_matching_only(self):
        graph = _small_graph()
        result = graphify_inspect.edges_by_relation(graph, "calls")
        assert result == [_edge("A", "B", "calls"), _edge("A", "C", "calls", score=0.8)]

    def test_edges_by_relation_no_match_returns_empty(self):
        graph = _small_graph()
        assert graphify_inspect.edges_by_relation(graph, "inherits") == []

    def test_relation_histogram_counts_all_relations(self):
        graph = _small_graph()
        assert graphify_inspect.relation_histogram(graph) == {"calls": 2, "imports": 1}

    def test_relation_histogram_on_empty_graph_is_empty_dict(self):
        assert graphify_inspect.relation_histogram(_empty_graph()) == {}
