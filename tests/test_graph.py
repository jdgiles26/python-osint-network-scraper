from src.domain.graph import build_relation_graph


def test_build_relation_graph_links_page_to_email():
    rows = [{
        "SourceURL": "https://example.com/a",
        "Title": "Example",
        "Entities": {"email": ["ada@example.com"]},
    }]
    graph = build_relation_graph(rows)
    ids = {node.id for node in graph.nodes}
    assert "https://example.com/a" in ids
    assert "email:ada@example.com" in ids
    page = next(node for node in graph.nodes if node.id == "https://example.com/a")
    assert page.group == "domain"
    assert page.label == "example.com"
    assert graph.edges[0].source == "https://example.com/a"
    assert graph.edges[0].target == "email:ada@example.com"
    assert graph.edges[0].relation == "email"


def test_live_entity_keys_are_not_renamed():
    rows = [{
        "SourceURL": "https://example.com/a",
        "Entities": {"emails": ["ada@example.com"], "phones": ["15551212"]},
    }]
    graph = build_relation_graph(rows)
    assert any(node.id == "emails:ada@example.com" and node.group == "emails" for node in graph.nodes)
    assert any(edge.relation == "phones" for edge in graph.edges)


def test_json_string_and_python_repr_both_link():
    payload = '{"email": ["ada@example.com"]}'
    repr_payload = str({"email": ["ada@example.com"]})
    for entities in (payload, repr_payload):
        graph = build_relation_graph([{"SourceURL": "https://example.com/a", "Entities": entities}])
        assert graph.edges[0].target == "email:ada@example.com"


def test_invalid_entities_keep_the_page_and_add_no_edges():
    graph = build_relation_graph([{"SourceURL": "https://example.com/a", "Entities": "not-json"}])
    assert [node.id for node in graph.nodes] == ["https://example.com/a"]
    assert graph.edges == []


def test_empty_and_non_dict_rows_add_nothing():
    graph = build_relation_graph([
        "skip",
        {"SourceURL": "", "Entities": {"email": ["ada@example.com"]}},
        {"SourceURL": "https://example.com/a", "Entities": {"email": ["", 3]}},
        {"SourceURL": "notevenaurl", "Entities": {"email": "ada@example.com"}},
    ])
    assert any(node.id == "notevenaurl" and node.label == "notevenaurl" for node in graph.nodes)
    assert any(node.id == "email:ada@example.com" for node in graph.nodes)
    assert all(edge.source == "notevenaurl" for edge in graph.edges)
