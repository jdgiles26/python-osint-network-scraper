from src.domain.graph import GraphEdge, GraphNode, RelationGraph
from src.infrastructure.report_html import render_report_html


def _graph():
    return RelationGraph(
        nodes=[
            GraphNode("https://example.com", "example.com", "domain"),
            GraphNode("email:ada@example.com", "ada@example.com", "email"),
        ],
        edges=[GraphEdge("https://example.com", "email:ada@example.com", "email")],
    )


def test_report_has_filters_search_and_testid():
    html = render_report_html(_graph(), title="OSINT Relationship Map")
    assert 'data-testid="report-title"' in html
    assert "OSINT Relationship Map" in html
    assert 'data-testid="graph-search"' in html
    assert 'data-testid="group-filter-email"' in html
    assert 'data-testid="group-filter-domain"' in html
    assert 'data-testid="network"' in html
    assert 'data-testid="graph-legend"' in html
    assert 'data-testid="node-detail"' in html
    assert "ada@example.com" in html
    assert 'data-testid="report-stats"' in html
    assert 'data-testid="relation-list"' in html
    assert "unpkg.com" not in html
    assert "vis.Network" not in html


def test_report_escapes_title_and_script_closer():
    graph = RelationGraph(
        nodes=[GraphNode("https://example.com", "</script><b>", "domain")],
        edges=[],
    )
    html = render_report_html(graph, title="A < B & C")
    assert html.count("</script>") == 2
    assert "\\u003c/script>" in html
    assert "</script><b>" not in html
    assert "A &lt; B &amp; C" in html
