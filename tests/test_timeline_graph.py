import random

import pytest

from src.timeline import GraphError, GraphState, diff


def node(name, kind="character"):
    return {"op": "add_node", "id": name, "name": name, "type": kind}


def test_graph_ops_are_atomic_and_normalise_types():
    graph = GraphState()
    graph.apply([node("A", "monster"), node("B", "location")])
    assert graph.nodes["A"]["type"] == "character"
    assert graph.nodes["A"]["subtype"] == "monster"
    original = graph.copy()
    with pytest.raises(GraphError, match="dangling"):
        graph.apply([node("C"), {"op": "add_edge", "id": "bad", "source": "C", "target": "D", "relation": "near"}])
    assert graph == original
    for bad in ([{"op": "mystery", "id": "x"}],
                [{"op": "update_node", "id": "missing", "name": "X"}],
                [{"op": "delete_edge", "id": "missing"}],
                [{"op": "add_node", "id": "bad", "name": "Bad", "type": 23}]):
        with pytest.raises(GraphError):
            graph.apply(bad)
        assert graph == original


def test_multiedges_delete_node_and_reverse():
    before = GraphState()
    before.apply([node("A"), node("B")])
    after = before.copy()
    after.apply([{"op": "add_edge", "id": "e1", "source": "A", "target": "B", "relation": "knows"},
                 {"op": "add_edge", "id": "e2", "source": "A", "target": "B", "relation": "owes"}])
    assert len(after.edges) == 2
    change = diff(before, after)
    assert change.apply_reverse(change.apply_forward(before.copy())) == before
    removed = after.copy()
    removed.apply([{"op": "delete_node", "id": "A"}])
    assert removed.edges == {}
    assert diff(after, removed).apply_reverse(removed.copy()) == after


def test_seeded_random_delta_round_trips():
    rng = random.Random(3381)
    graph = GraphState()
    for index in range(160):
        before = graph.copy()
        available = list(graph.nodes)
        choice = rng.choice(["node", "edge", "update", "delete"])
        if choice == "node" or not available:
            graph.apply([node(f"n{index}")])
        elif choice == "edge" and len(available) >= 2:
            graph.apply([{"op": "add_edge", "id": f"e{index}", "source": available[0],
                          "target": available[-1], "relation": "link"}])
        elif choice == "delete":
            graph.apply([{"op": "delete_node", "id": rng.choice(available)}])
        else:
            graph.apply([{"op": "update_node", "id": rng.choice(available), "description": str(index)}])
        delta = diff(before, graph)
        assert delta.apply_forward(before.copy()) == graph
        assert delta.apply_reverse(graph.copy()) == before
