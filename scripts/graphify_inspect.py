#!/usr/bin/env python3
"""Ad-hoc graph.json inspection helper (replaces hand-rolled json.load + dict-poking).

Works directly on an in-memory NetworkX node-link graph dict, plus a
`load_graph` convenience that reads graph.json off disk and normalizes the
legacy "edges" key to "links" (mirroring graphify.build's own tolerance).

Run: python3 scripts/graphify_inspect.py summary graphify-out/graph.json
"""
from __future__ import annotations

import argparse
import json


def load_graph(path) -> dict:
    """Read graph.json from path; normalize "edges" key to "links" if needed."""
    with open(path, "r", encoding="utf-8") as f:
        graph = json.load(f)
    if "links" not in graph and "edges" in graph:
        graph = dict(graph, links=graph["edges"])
    return graph


def summary(graph: dict) -> dict:
    nodes = graph.get("nodes", [])
    links = graph.get("links", [])
    communities = {n.get("community") for n in nodes if n.get("community") is not None}
    return {
        "nodes": len(nodes),
        "edges": len(links),
        "hyperedges": len(graph.get("hyperedges", [])),
        "communities": len(communities),
        "directed": graph.get("directed", True),
        "multigraph": graph.get("multigraph", False),
        "built_at_commit": graph.get("built_at_commit"),
    }


def get_node(graph: dict, node_id) -> dict | None:
    for node in graph.get("nodes", []):
        if node.get("id") == node_id:
            return node
    return None


def neighbors(graph: dict, node_id) -> list[dict]:
    result = []
    for link in graph.get("links", []):
        source, target = link.get("source"), link.get("target")
        if source == node_id:
            result.append({"neighbor": target, "relation": link.get("relation"), "direction": "out"})
        elif target == node_id:
            result.append({"neighbor": source, "relation": link.get("relation"), "direction": "in"})
    return result


def nodes_in_community(graph: dict, community: int) -> list[dict]:
    return [n for n in graph.get("nodes", []) if n.get("community") == community]


def edges_by_relation(graph: dict, relation: str) -> list[dict]:
    return [link for link in graph.get("links", []) if link.get("relation") == relation]


def relation_histogram(graph: dict) -> dict[str, int]:
    histogram: dict[str, int] = {}
    for link in graph.get("links", []):
        relation = link.get("relation")
        histogram[relation] = histogram.get(relation, 0) + 1
    return histogram


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a graphify graph.json")
    sub = parser.add_subparsers(dest="command", required=True)

    p_summary = sub.add_parser("summary", help="print node/edge/community counts")
    p_summary.add_argument("graph_path")

    p_node = sub.add_parser("node", help="print a node's full attribute dict")
    p_node.add_argument("graph_path")
    p_node.add_argument("node_id")

    p_neighbors = sub.add_parser("neighbors", help="list a node's incident edges")
    p_neighbors.add_argument("graph_path")
    p_neighbors.add_argument("node_id")

    p_community = sub.add_parser("community", help="list nodes in a community")
    p_community.add_argument("graph_path")
    p_community.add_argument("community", type=int)

    p_relation = sub.add_parser("relation", help="list edges of a given relation")
    p_relation.add_argument("graph_path")
    p_relation.add_argument("relation")

    p_relations = sub.add_parser("relations", help="print relation histogram")
    p_relations.add_argument("graph_path")

    args = parser.parse_args()
    graph = load_graph(args.graph_path)

    if args.command == "summary":
        print(json.dumps(summary(graph), indent=2))
    elif args.command == "node":
        node = get_node(graph, args.node_id)
        print(json.dumps(node, indent=2) if node else f"no node with id {args.node_id!r}")
    elif args.command == "neighbors":
        for entry in neighbors(graph, args.node_id):
            print(f"{entry['direction']:>3}  {entry['neighbor']}  ({entry['relation']})")
    elif args.command == "community":
        for node in nodes_in_community(graph, args.community):
            print(f"{node.get('id')}  {node.get('label')}")
    elif args.command == "relation":
        for link in edges_by_relation(graph, args.relation):
            print(f"{link.get('source')} --{link.get('relation')}--> {link.get('target')}")
    elif args.command == "relations":
        for relation, count in sorted(relation_histogram(graph).items()):
            print(f"{relation}: {count}")


if __name__ == "__main__":
    main()
