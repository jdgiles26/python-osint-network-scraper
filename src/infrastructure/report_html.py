import html
import json


def _payload(graph) -> str:
    data = {
        "nodes": [
            {"id": node.id, "label": node.label, "group": node.group}
            for node in graph.nodes
        ],
        "edges": [
            {"source": edge.source, "target": edge.target, "relation": edge.relation}
            for edge in graph.edges
        ],
    }
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def _node_label(graph, node_id: str) -> str:
    for node in graph.nodes:
        if node.id == node_id:
            return node.label
    return node_id


def render_report_html(graph, title: str) -> str:
    groups = []
    for node in graph.nodes:
        if node.group not in groups:
            groups.append(node.group)
    filters = []
    legend = []
    for group in groups:
        safe_group = html.escape(group, quote=True)
        count = sum(1 for node in graph.nodes if node.group == group)
        filters.append(
            f'<button type="button" class="filter on" data-testid="group-filter-{safe_group}" '
            f'data-group="{safe_group}" aria-label="{safe_group}">{safe_group} <span>{count}</span></button>'
        )
        legend.append(f'<li data-group="{safe_group}"><i data-group="{safe_group}"></i>{safe_group} · {count}</li>')
    relations = []
    for edge in graph.edges:
        relations.append(
            "<li>"
            f'<span class="rel">{html.escape(edge.relation)}</span> '
            f'{html.escape(_node_label(graph, edge.source))} → {html.escape(_node_label(graph, edge.target))}'
            "</li>"
        )
    pages = sum(1 for node in graph.nodes if node.group == "domain")
    entities = len(graph.nodes) - pages
    safe_title = html.escape(title, quote=True)
    relation_html = "".join(relations) or "<li>No relationships in this crawl.</li>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
:root {{ color-scheme: dark; --bg:#0b1020; --panel:#141b2d; --ink:#e8eefc; --muted:#93a0bd; --line:#2a3550; --accent:#6ee7d2; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font:15px/1.45 "Avenir Next", "Segoe UI", sans-serif; background:radial-gradient(1200px 500px at 10% -10%, #1c2b4a, transparent), var(--bg); color:var(--ink); }}
header {{ display:flex; justify-content:space-between; gap:24px; align-items:end; padding:28px 28px 8px; }}
h1 {{ margin:0; font-size:32px; letter-spacing:-0.04em; }}
.sub {{ margin:6px 0 0; color:var(--muted); }}
.stats {{ display:flex; gap:10px; }}
.stat {{ min-width:92px; background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:10px 12px; }}
.stat b {{ display:block; font-size:22px; }}
.stat span {{ color:var(--muted); font-size:12px; }}
.layout {{ display:grid; grid-template-columns: 300px 1fr; gap:16px; padding:16px 28px 32px; }}
.panel {{ background:rgba(20,27,45,.92); border:1px solid var(--line); border-radius:16px; padding:14px; }}
label {{ display:block; color:var(--muted); font-size:12px; margin-bottom:6px; }}
input[type="search"] {{ width:100%; border:1px solid var(--line); background:#0b1020; color:var(--ink); border-radius:10px; padding:10px 12px; }}
.filters {{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }}
button.filter {{ border:1px solid var(--line); background:transparent; color:var(--ink); border-radius:999px; padding:6px 10px; cursor:pointer; }}
button.filter span {{ color:var(--muted); }}
button.filter.on {{ background:var(--accent); color:#06221e; border-color:transparent; }}
button.filter.on span {{ color:#06221e; }}
#network {{ min-height:680px; height:70vh; border:1px solid var(--line); border-radius:16px; background:#101828; position:relative; overflow:hidden; }}
svg {{ width:100%; height:100%; }}
circle, text {{ cursor:pointer; }}
#node-detail {{ min-height:120px; white-space:pre-wrap; }}
ul {{ margin:8px 0 0; padding-left:0; list-style:none; color:var(--muted); }}
li {{ margin:6px 0; }}
.rel {{ color:var(--accent); }}
h2 {{ font-size:13px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:16px 0 8px; }}
</style>
</head>
<body>
<header>
  <div>
    <h1 data-testid="report-title">{safe_title}</h1>
    <p class="sub">Pages on the left, found details on the right. Search and the chips hide what you do not need.</p>
  </div>
  <div class="stats" data-testid="report-stats">
    <div class="stat"><b>{pages}</b><span>Pages</span></div>
    <div class="stat"><b>{entities}</b><span>Details</span></div>
    <div class="stat"><b>{len(graph.edges)}</b><span>Links</span></div>
  </div>
</header>
<div class="layout">
  <aside class="panel">
    <label for="graph-search">Search</label>
    <input id="graph-search" data-testid="graph-search" type="search" aria-label="Search nodes" placeholder="Name, email, host">
    <div class="filters" data-testid="graph-filters">{''.join(filters)}</div>
    <h2>Legend</h2>
    <ul data-testid="graph-legend">{''.join(legend)}</ul>
    <h2>Selected</h2>
    <div id="node-detail" data-testid="node-detail">Select a node to see what it connects to.</div>
    <h2>Links</h2>
    <ul data-testid="relation-list">{relation_html}</ul>
  </aside>
  <section id="network" data-testid="network" aria-label="Relationship network"></section>
</div>
<script id="graph-data" type="application/json">{_payload(graph)}</script>
<script>
const graph = JSON.parse(document.getElementById("graph-data").textContent);
const enabled = new Set(graph.nodes.map(node => node.group));
const search = document.getElementById("graph-search");
const detail = document.getElementById("node-detail");
const host = document.getElementById("network");
const colors = {{ domain:"#8eb6ff", email:"#6ee7d2", emails:"#6ee7d2", phones:"#f0c05a", ipv4:"#f08a5d", socials:"#c084fc", crypto:"#f472b6", assets:"#94a3b8", metadata:"#a3e635" }};
let selected = "";
function colorOf(group) {{ return colors[group] || "#d6def2"; }}
function visible(node) {{
  const query = search.value.trim().toLowerCase();
  if (!enabled.has(node.group)) return false;
  if (!query) return true;
  return (node.label || "").toLowerCase().includes(query);
}}
function esc(value) {{
  return String(value).replace(/[&<>"]/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[ch]));
}}
function draw() {{
  const nodes = graph.nodes.filter(visible);
  const ids = new Set(nodes.map(node => node.id));
  const edges = graph.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target));
  const width = host.clientWidth || 900;
  const height = host.clientHeight || 680;
  const pages = nodes.filter(node => node.group === "domain");
  const details = nodes.filter(node => node.group !== "domain");
  const pos = {{}};
  function column(list, x) {{
    const gap = Math.max(36, (height - 48) / Math.max(list.length, 1));
    list.forEach((node, index) => {{ pos[node.id] = [x, 36 + index * gap]; }});
  }}
  column(pages, 180);
  column(details, width - 220);
  const lines = edges.map(edge => {{
    const [x1, y1] = pos[edge.source];
    const [x2, y2] = pos[edge.target];
    const hot = selected && (edge.source === selected || edge.target === selected);
    return `<line x1="${{x1}}" y1="${{y1}}" x2="${{x2}}" y2="${{y2}}" stroke="${{hot ? "#6ee7d2" : "#31415f"}}" stroke-width="${{hot ? 2.5 : 1}}" />`;
  }}).join("");
  const dots = nodes.map(node => {{
    const [x, y] = pos[node.id];
    const anchor = node.group === "domain" ? "end" : "start";
    const dx = node.group === "domain" ? -18 : 18;
    return `<g data-id="${{esc(node.id)}}"><circle cx="${{x}}" cy="${{y}}" r="${{selected === node.id ? 11 : 8}}" fill="${{colorOf(node.group)}}" /><text x="${{x + dx}}" y="${{y + 4}}" text-anchor="${{anchor}}" fill="#e8eefc" font-size="12">${{esc(node.label)}}</text></g>`;
  }}).join("");
  host.innerHTML = `<svg viewBox="0 0 ${{width}} ${{height}}">${{lines}}${{dots}}</svg>`;
  host.querySelectorAll("g").forEach(group => {{
    group.addEventListener("click", () => {{
      const node = graph.nodes.find(item => item.id === group.getAttribute("data-id"));
      if (!node) return;
      selected = node.id;
      const linked = graph.edges.filter(edge => edge.source === node.id || edge.target === node.id);
      const lines = linked.map(edge => {{
        const otherId = edge.source === node.id ? edge.target : edge.source;
        const other = graph.nodes.find(item => item.id === otherId);
        return (edge.relation || "link") + ": " + (other ? other.label : otherId);
      }});
      detail.textContent = node.label + "\\n" + node.group + "\\n" + node.id + (lines.length ? "\\n\\n" + lines.join("\\n") : "\\n\\nNo links in the current filter.");
      draw();
    }});
  }});
}}
document.querySelectorAll("button.filter").forEach(button => {{
  button.addEventListener("click", () => {{
    const group = button.getAttribute("data-group");
    if (enabled.has(group)) enabled.delete(group); else enabled.add(group);
    button.classList.toggle("on");
    draw();
  }});
}});
search.addEventListener("input", draw);
draw();
</script>
</body>
</html>
"""
