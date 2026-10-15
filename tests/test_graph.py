from src.domain.graph import build_relation_graph, filter_relation_graph


def test_build_relation_graph_links_page_to_email():
    rows = [{
        "SourceURL": "https://example.com/a",
        "Title": "Example",
        "Entities": {"email": ["ada@example.com"]},
    }]
    graph = build_relation_graph(rows)
    email = next(node for node in graph.nodes if node.type == "EMAIL")
    assert email.id == "EMAIL:ada@example.com"
    assert email.value == "ada@example.com"
    assert email.confidence == 0.98
    page = next(node for node in graph.nodes if node.type == "DOMAIN")
    assert page.id == "DOMAIN:example.com"
    assert page.label == "example.com"
    assert page.group == "web"
    assert graph.edges[0].source == "DOMAIN:example.com"
    assert graph.edges[0].target == "EMAIL:ada@example.com"
    assert graph.edges[0].relation == "ASSOCIATED_WITH"


def test_entity_keys_become_canonical_types():
    rows = [{
        "SourceURL": "https://example.com/a",
        "Entities": {"emails": ["Ada@Example.com"], "phones": ["(555) 010-0199"]},
    }]
    graph = build_relation_graph(rows)
    assert any(node.id == "EMAIL:ada@example.com" and node.group == "contact" for node in graph.nodes)
    assert any(node.value == "+15550100199" and node.type == "PHONE" for node in graph.nodes)
    assert any(edge.relation == "HAS_PHONE" for edge in graph.edges)
    assert all(not node.id.startswith("emails:") and not node.id.startswith("phones:") for node in graph.nodes)


def test_json_string_and_python_repr_both_link():
    payload = '{"email": ["ada@example.com"]}'
    repr_payload = str({"email": ["ada@example.com"]})
    for entities in (payload, repr_payload):
        graph = build_relation_graph([{"SourceURL": "https://example.com/a", "Entities": entities}])
        assert graph.edges[0].target == "EMAIL:ada@example.com"


def test_invalid_entities_add_no_nodes():
    graph = build_relation_graph([{"SourceURL": "https://example.com/a", "Entities": "not-json"}])
    assert graph.nodes == []
    assert graph.edges == []


def test_empty_and_non_dict_rows_keep_only_real_assertions():
    graph = build_relation_graph([
        "skip",
        {"SourceURL": "", "Entities": {"email": ["ada@example.com"]}},
        {"SourceURL": "https://example.com/a", "Entities": {"email": ["", 3]}},
        {"SourceURL": "notevenaurl", "Entities": {"email": "ada@example.com"}},
    ])
    assert any(node.id == "DOMAIN:notevenaurl" and node.label == "notevenaurl" for node in graph.nodes)
    assert any(node.id == "EMAIL:ada@example.com" for node in graph.nodes)
    assert graph.edges
    assert all(edge.source == "DOMAIN:notevenaurl" for edge in graph.edges)


def test_phone_filter_keeps_the_source_edge():
    rows = [{
        "SourceURL": "https://example.com/athlete",
        "Entities": {"phones": ["(555) 010-0199"], "metadata": ["breadcrumb: Home"]},
    }]
    graph = build_relation_graph(rows)
    view = filter_relation_graph(graph, category="PHONE")
    ids = {node.id for node in view.nodes}
    assert "PHONE:+15550100199" in ids
    assert "DOMAIN:example.com" in ids
    assert all(node.type != "PROVENANCE" for node in view.nodes)
    assert view.edges
    assert {edge.source for edge in view.edges} == {"DOMAIN:example.com"}
    linked = {edge.source for edge in view.edges} | {edge.target for edge in view.edges}
    assert ids <= linked
