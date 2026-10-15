import re

from src.domain.graph import GraphEdge, GraphNode, RelationGraph, build_relation_graph
from src.infrastructure.report_html import render_report_html


def _graph():
    return build_relation_graph([{
        "SourceURL": "https://example.com/a",
        "Entities": {"email": ["ada@example.com"]},
    }])


def _app_script(html):
    marker = '<script id="report-app">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return html[start:end]


def _outside_scripts(html):
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)


def test_report_has_three_panes_and_entity_filters():
    html = render_report_html(_graph(), title="OSINT Relationship Map")
    assert 'data-testid="report-title"' in html
    assert "OSINT Relationship Map" in html
    assert 'data-testid="report-layout"' in html
    assert 'data-testid="filter-pane"' in html
    assert 'data-testid="network"' in html
    assert 'data-testid="inspector-pane"' in html
    assert 'data-testid="graph-search"' in html
    assert 'data-testid="group-filter-people"' in html
    assert 'data-testid="group-filter-contact"' in html
    assert 'data-testid="group-filter-locations"' in html
    assert 'data-testid="group-filter-web"' in html
    assert ">People <" in html
    assert ">Contact Points <" in html
    assert ">Locations <" in html
    assert ">Web Footprint <" in html
    assert 'data-testid="graph-legend"' in html
    assert 'data-testid="node-detail"' in html
    assert 'data-testid="verify-entity"' in html
    assert 'data-testid="reject-entity"' in html
    assert "ada@example.com" in html
    assert 'data-testid="report-stats"' in html
    assert 'data-testid="relation-list"' in html
    assert 'data-windowed="1"' in html
    assert "unpkg.com" not in html
    assert "vis.Network" not in html
    assert "createStore" in html
    assert "DOMPurify" in html
    assert "transferControlToOffscreen" in html
    assert "OffscreenCanvas" in _app_script(html) or "transferControlToOffscreen" in _app_script(html)
    app = _app_script(html)
    assert "innerHTML" not in app
    assert "eval(" not in app
    assert "DOMPurify.sanitize" in app
    assert "new Worker" in app
    assert "nodeToEdges" in app
    assert "edgeToNodes" in app
    assert "function layoutGraph" in app
    assert "createStore" in app


def test_report_escapes_title_and_script_closer():
    graph = RelationGraph(
        nodes=[GraphNode("https://example.com", "</script><b>", "domain")],
        edges=[],
    )
    html = render_report_html(graph, title="A < B & C")
    assert html.count("</script>") == 3
    assert "\\u003c/script>" in html
    assert "</script><b>" not in html
    assert "A &lt; B &amp; C" in html


def test_sidebar_does_not_emit_one_row_per_edge():
    rows = [{
        "SourceURL": "https://example.com/a",
        "Entities": {"emails": [f"user{i}@example.com" for i in range(500)]},
    }]
    graph = build_relation_graph(rows)
    assert len(graph.edges) >= 500
    html = render_report_html(graph, title="Big")
    outside = _outside_scripts(html)
    assert outside.count("<li") < 20
    assert 'class="rel-row"' not in outside
    assert outside.count("<button") < 20
    assert "user499@example.com" not in outside
    assert 'data-windowed="1"' in html


def test_report_opens_on_findings_and_names_connections():
    graph = RelationGraph(
        nodes=[
            GraphNode("DOMAIN:example.com", "example.com", "web", type="DOMAIN", value="example.com", confidence=1),
            GraphNode("PERSON:ada", "Ada Lovelace", "people", type="PERSON", value="Ada Lovelace", confidence=0.85),
            GraphNode("PROVENANCE:site", "twitter:site", "web", type="PROVENANCE", value="@site", confidence=0.5),
        ],
        edges=[
            GraphEdge("DOMAIN:example.com", "PERSON:ada", "ASSOCIATED_WITH"),
            GraphEdge("DOMAIN:example.com", "PROVENANCE:site", "ASSOCIATED_WITH"),
        ],
    )
    html = render_report_html(graph, title="Findings")
    assert 'data-testid="group-filter-people" data-category="people" aria-pressed="true"' in html
    assert 'data-testid="group-filter-locations" data-category="locations" aria-pressed="false"' in html
    assert 'data-testid="group-filter-web" data-category="web" aria-pressed="false"' in html
    assert "page metadata" in html
    assert 'data-testid="view-hint"' in html
    app = _app_script(html)
    assert "Found here" in app
    assert "Found on" in app
    assert "Also on this source" in app
    assert "named on" in app
    assert "page details hidden" in app
    assert "function layoutGraph" in app
    assert "innerHTML" not in app
    assert "eval(" not in app


def test_metadata_only_report_still_shows_web_footprint():
    graph = RelationGraph(
        nodes=[
            GraphNode("DOMAIN:example.com", "example.com", "web", type="DOMAIN", value="example.com", confidence=1),
            GraphNode("PROVENANCE:site", "og:site", "web", type="PROVENANCE", value="og:site", confidence=0.5),
        ],
        edges=[GraphEdge("DOMAIN:example.com", "PROVENANCE:site", "ASSOCIATED_WITH")],
    )
    html = render_report_html(graph, title="Meta")
    assert 'data-testid="group-filter-web" data-category="web" aria-pressed="true"' in html


def test_manual_edge_still_renders():
    graph = RelationGraph(
        nodes=[
            GraphNode("DOMAIN:example.com", "example.com", "web", type="DOMAIN", value="example.com", confidence=1),
            GraphNode("EMAIL:ada@example.com", "ada@example.com", "contact", type="EMAIL", value="ada@example.com", confidence=0.98),
        ],
        edges=[GraphEdge("DOMAIN:example.com", "EMAIL:ada@example.com", "ASSOCIATED_WITH")],
    )
    html = render_report_html(graph, title="Manual")
    assert "ASSOCIATED_WITH" in html
    assert "ada@example.com" in html
