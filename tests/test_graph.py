from rusted_recall.graph import DependencyGraph


def build_graph() -> DependencyGraph:
    g = DependencyGraph()
    g.add_edge("sot", "master", "explicit_declaration", 1.0)
    g.add_edge("master", "hero", "parent_child_derivation", 0.9)
    g.add_edge("hero", "crop", "phash_derivative", 0.8)
    g.add_edge("master", "banner", "visual_similarity", 0.7)
    return g


def test_reachable_multi_hop():
    g = build_graph()
    reachable = g.reachable("sot")
    assert {"master", "hero", "crop", "banner"} <= reachable


def test_strongest_path_returns_explanation():
    g = build_graph()
    paths = g.strongest_paths("sot")
    crop = paths["crop"]
    assert crop.nodes == ["sot", "master", "hero", "crop"]
    assert crop.depth == 3
    assert "-->" in crop.describe()


def test_cycle_is_safe():
    g = DependencyGraph()
    g.add_edge("a", "b", "x", 1.0)
    g.add_edge("b", "a", "x", 1.0)
    g.add_edge("b", "c", "x", 1.0)
    reachable = g.reachable("a")
    # 'a' is not revisited within a path (cycle-safe), so it is not in its own
    # reachable set; traversal terminates rather than looping.
    assert reachable == {"b", "c"}


def test_max_depth_limits_traversal():
    g = DependencyGraph()
    for i in range(10):
        g.add_edge(str(i), str(i + 1), "x", 1.0)
    paths = g.strongest_paths("0", max_depth=3)
    assert "3" in paths
    assert "4" not in paths


def test_confidence_decays_with_depth():
    g = build_graph()
    paths = g.strongest_paths("sot")
    assert paths["master"].strength > paths["crop"].strength
