import json
import sys
import networkx as nx
import pytest
from pathlib import Path
from graphify.build import build_from_json
from graphify.cluster import cluster, cohesion_score, remap_communities_to_previous, score_all, _partition

FIXTURES = Path(__file__).parent / "fixtures"

def make_graph():
    return build_from_json(json.loads((FIXTURES / "extraction.json").read_text()))

def test_cluster_returns_dict():
    G = make_graph()
    communities = cluster(G)
    assert isinstance(communities, dict)

def test_cluster_covers_all_nodes():
    G = make_graph()
    communities = cluster(G)
    all_nodes = {n for nodes in communities.values() for n in nodes}
    assert all_nodes == set(G.nodes)

def test_cohesion_score_complete_graph():
    G = nx.complete_graph(4)
    G = nx.relabel_nodes(G, {i: str(i) for i in G.nodes})
    score = cohesion_score(G, list(G.nodes))
    assert score == 1.0

def test_cohesion_score_single_node():
    G = nx.Graph()
    G.add_node("a")
    score = cohesion_score(G, ["a"])
    assert score == 1.0

def test_cohesion_score_disconnected():
    G = nx.Graph()
    G.add_nodes_from(["a", "b", "c"])
    score = cohesion_score(G, ["a", "b", "c"])
    assert score == 0.0

def test_cohesion_score_range():
    G = make_graph()
    communities = cluster(G)
    for cid, nodes in communities.items():
        score = cohesion_score(G, nodes)
        assert 0.0 <= score <= 1.0

def test_score_all_keys_match_communities():
    G = make_graph()
    communities = cluster(G)
    scores = score_all(G, communities)
    assert set(scores.keys()) == set(communities.keys())


def test_cluster_uses_graspologic_native_when_available():
    """Regression test for the graspologic -> graspologic-native swap.

    When graspologic_native is importable, cluster() must route through its
    Leiden implementation end-to-end (via _partition) and still return a
    complete, non-empty partition that covers every node in the graph -
    i.e. the native-library integration must not silently drop nodes.
    """
    pytest.importorskip("graspologic_native")
    G = make_graph()
    communities = cluster(G)
    assert isinstance(communities, dict)
    assert communities
    all_nodes = {n for nodes in communities.values() for n in nodes}
    assert all_nodes == set(G.nodes)


def test_cluster_falls_back_to_louvain_without_graspologic_native(monkeypatch):
    """Regression test for the Louvain fallback branch of _partition().

    Simulates graspologic_native being unavailable (regardless of whether
    it's actually installed on the machine running this test) by making the
    import raise ImportError. cluster() must still return a complete,
    non-empty partition via networkx's louvain_communities so the fallback
    path can't silently break even on dev machines that always have
    graspologic-native installed.
    """
    monkeypatch.setitem(sys.modules, "graspologic_native", None)
    G = make_graph()
    communities = cluster(G)
    assert isinstance(communities, dict)
    assert communities
    all_nodes = {n for nodes in communities.values() for n in nodes}
    assert all_nodes == set(G.nodes)


def test_partition_result_is_deterministic():
    """Regression test locking in the seed=42 determinism contract.

    Callers such as community_member_sigs() fingerprint community
    membership and rely on _partition() producing the same node ->
    community assignment across runs on the same graph. Two consecutive
    calls on an identical graph must return identical partitions.
    """
    G = nx.Graph()
    G.add_edges_from([
        ("a", "b"), ("b", "c"), ("a", "c"),
        ("c", "d"),
        ("d", "e"), ("e", "f"), ("d", "f"),
    ])
    partition1 = _partition(G, resolution=1.0)
    partition2 = _partition(G, resolution=1.0)
    assert partition1 == partition2


def test_cluster_does_not_write_to_stdout(capsys):
    """Clustering should not emit ANSI escape codes or other output.

    graspologic's leiden() can emit ANSI escape sequences that break
    PowerShell 5.1's scroll buffer on Windows (issue #19). The output
    suppression in _partition() should prevent any output from leaking.
    """
    G = make_graph()
    cluster(G)
    captured = capsys.readouterr()
    assert captured.out == "", f"cluster() wrote to stdout: {captured.out!r}"


def test_cluster_does_not_write_to_stderr(capsys):
    """Same as above but for stderr — ANSI codes can go to either stream."""
    G = make_graph()
    cluster(G)
    captured = capsys.readouterr()
    # Allow logging output (starts with [graphify]) but no raw ANSI codes
    for line in captured.err.splitlines():
        assert "\x1b" not in line, f"cluster() wrote ANSI to stderr: {line!r}"


def test_remap_communities_to_previous_reuses_old_ids():
    communities = {
        10: ["a", "b", "c"],
        11: ["d", "e"],
    }
    previous = {"a": 5, "b": 5, "c": 5, "d": 1, "e": 1}
    remapped = remap_communities_to_previous(communities, previous)
    assert set(remapped.keys()) == {1, 5}
    assert remapped[5] == ["a", "b", "c"]
    assert remapped[1] == ["d", "e"]


def test_remap_communities_to_previous_assigns_deterministic_new_ids():
    communities = {
        7: ["x", "y", "z"],
        8: ["m"],
    }
    previous = {"a": 3}
    remapped = remap_communities_to_previous(communities, previous)
    assert list(remapped.keys()) == [0, 1]
    assert remapped[0] == ["x", "y", "z"]
    assert remapped[1] == ["m"]
