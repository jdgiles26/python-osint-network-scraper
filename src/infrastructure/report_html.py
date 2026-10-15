"""Self-contained three-pane OSINT report.

DOMPurify, Zod, and Zustand are inlined as classic scripts so the file opens
from disk with no build step and no network.
"""
import html
import json
import re
from pathlib import Path


_VENDOR_PATH = Path(__file__).with_name("vendor") / "browser_libs.js"
_APP_PATH = Path(__file__).with_name("report_app.js")
_FILTERS = (
    ("people", "People"),
    ("contact", "Contact Points"),
    ("locations", "Locations"),
    ("web", "Web Footprint"),
)


def _safe_script(source: str) -> str:
    return re.sub(r"</script", r"<\\/script", source, flags=re.IGNORECASE)


def _payload(graph) -> str:
    nodes = []
    for node in graph.nodes:
        observations = []
        for item in getattr(node, "observations", ()) or ():
            observations.append({
                "sourceDomain": str(item.get("sourceDomain", "")),
                "rawMetadataKey": str(item.get("rawMetadataKey", "")),
                "confidence": float(item.get("confidence", 0) or 0),
            })
        value = getattr(node, "value", None)
        if value is None or value == "":
            value = node.label
        nodes.append({
            "id": node.id,
            "label": node.label,
            "group": node.group,
            "type": getattr(node, "type", None) or "PROVENANCE",
            "value": value,
            "confidence": float(getattr(node, "confidence", 0) or 0),
            "sourceDomain": getattr(node, "source_domain", "") or "",
            "rawMetadataKey": getattr(node, "raw_metadata_key", "") or "",
            "observations": observations,
        })
    edges = []
    for edge in graph.edges:
        edges.append({
            "id": edge.id or f"{edge.source}|{edge.relation}|{edge.target}",
            "source": edge.source,
            "target": edge.target,
            "predicate": edge.relation,
        })
    encoded = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)
    return encoded.replace("<", "\\u003c")


def _counts(graph):
    counts = {key: 0 for key, _label in _FILTERS}
    for node in graph.nodes:
        if getattr(node, "type", "") == "DOMAIN":
            continue
        group = getattr(node, "group", "")
        if group in counts:
            counts[group] += 1
    return counts


def _has_findings(counts) -> bool:
    return bool(counts["people"] or counts["contact"] or counts["locations"])


def _findings_blurb(counts) -> str:
    parts = []
    people = counts["people"]
    contact = counts["contact"]
    locations = counts["locations"]
    if people:
        parts.append(f"{people} person" if people == 1 else f"{people} people")
    if contact:
        parts.append(f"{contact} contact point" if contact == 1 else f"{contact} contact points")
    if locations:
        parts.append(f"{locations} place" if locations == 1 else f"{locations} places")
    if not parts:
        found = "findings"
    elif len(parts) == 1:
        found = parts[0]
    elif len(parts) == 2:
        found = f"{parts[0]} and {parts[1]}"
    else:
        found = ", ".join(parts[:-1]) + ", and " + parts[-1]
    hidden = counts["web"]
    if hidden == 1:
        tail = "1 page metadata record stays in Web footprint until you turn it on."
    elif hidden:
        tail = f"{hidden} page metadata records stay in Web footprint until you turn it on."
    else:
        tail = "Page metadata such as site names stays in Web footprint until you turn it on."
    return (
        f"This crawl found {found}. Each one is drawn with the source that mentioned it. {tail}"
    )


def _filter_on(key: str, counts) -> bool:
    """Page metadata, and empty groups, stay off when the crawl found something."""
    if not _has_findings(counts):
        return True
    if key == "web":
        return False
    return counts.get(key, 0) > 0


_STYLE = """
:root { color-scheme: dark; --bg:#070b14; --panel:#121a2b; --ink:#f4f7ff; --muted:#93a0bd; --line:#2c3a56; --accent:#6ee7d2; --warn:#f0a0a0; --gold:#f0c05a; --blue:#8eb6ff; --violet:#c084fc; }
* { box-sizing: border-box; }
body { margin:0; min-height:100vh; font:15px/1.45 "Avenir Next", "Segoe UI", sans-serif; background:radial-gradient(900px 420px at 0% -10%, rgba(110,231,210,.10), transparent 55%), radial-gradient(800px 420px at 100% 0%, rgba(142,182,255,.08), transparent 50%), var(--bg); color:var(--ink); }
header { display:flex; justify-content:space-between; gap:24px; align-items:flex-end; padding:20px 28px 0; }
h1 { margin:0; font-size:28px; letter-spacing:-0.04em; font-weight:680; }
h2 { font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:16px 0 8px; }
.kicker { margin:0 0 4px; color:var(--accent); font-size:11px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }
.sub { margin:8px 0 0; color:var(--muted); max-width:70ch; }
.stats { display:flex; gap:10px; }
.stat { min-width:96px; background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:10px 14px; }
.stat b { display:block; font-size:22px; letter-spacing:-0.03em; }
.stat span { color:var(--muted); font-size:12px; }
.layout { display:grid; grid-template-columns:minmax(320px, 400px) minmax(0, 1fr) minmax(300px, 380px); gap:14px; padding:14px 28px 22px; height:calc(100vh - 112px); min-height:640px; }
.panel { background:rgba(18,26,43,.94); border:1px solid var(--line); border-radius:18px; padding:16px; min-width:0; min-height:0; display:flex; flex-direction:column; overflow:hidden; }
label { display:block; color:var(--muted); font-size:12px; margin-bottom:6px; }
input[type="search"] { width:100%; border:1px solid var(--line); background:#0b1020; color:var(--ink); border-radius:12px; padding:11px 12px; font:inherit; }
input[type="search"]:focus { outline:2px solid rgba(110,231,210,.45); border-color:transparent; }
.filters { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 0; }
button.filter { display:inline-flex; align-items:center; gap:7px; border:1px solid var(--line); background:transparent; color:var(--ink); border-radius:999px; padding:7px 12px; cursor:pointer; font:inherit; font-size:13px; }
button.filter::before { content:""; width:8px; height:8px; border-radius:99px; background:var(--muted); }
button.filter[data-category="people"]::before { background:var(--accent); }
button.filter[data-category="contact"]::before { background:var(--gold); }
button.filter[data-category="locations"]::before { background:var(--blue); }
button.filter[data-category="web"]::before { background:var(--violet); }
button.filter span { color:var(--muted); font-variant-numeric:tabular-nums; }
button.filter.on { background:var(--accent); color:#06221e; border-color:transparent; font-weight:700; }
button.filter.on span { color:#06221e; }
button.filter:not(.on) { opacity:.72; }
button.filter:focus-visible, button.conn:focus-visible, .rel-row:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.hint { margin:10px 0 0; color:var(--muted); font-size:13px; }
#network { min-height:0; height:100%; border-radius:18px; border:1px solid var(--line); background:#101828; position:relative; overflow:hidden; }
#graph-canvas { display:block; width:100%; height:100%; }
#node-detail { flex:1 1 auto; min-height:0; overflow:auto; }
#node-detail .value { margin:0; font-size:26px; line-height:1.15; letter-spacing:-0.03em; font-weight:680; overflow-wrap:anywhere; }
#node-detail .kind { margin:6px 0 0; color:var(--accent); font-size:13px; font-weight:700; }
#node-detail h3 { font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:18px 0 8px; }
#node-detail .meta { margin:6px 0; color:var(--muted); font-size:13px; }
#node-detail .meta b { display:inline-block; min-width:92px; color:var(--muted); font-weight:650; }
.conn-list { display:flex; flex-direction:column; gap:6px; }
button.conn { display:flex; align-items:center; gap:8px; width:100%; text-align:left; border:1px solid var(--line); background:#0b1020; color:var(--ink); border-radius:12px; padding:8px 10px; cursor:pointer; font:inherit; }
button.conn:hover { border-color:var(--accent); }
button.conn .conn-label { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
button.conn .conn-type { flex:0 0 auto; color:var(--muted); font-size:12px; }
#verification-status { margin:8px 0 0; font-weight:700; color:var(--accent); }
.verify-row { display:flex; gap:8px; margin-top:12px; flex:0 0 auto; }
#verification-status { flex:0 0 auto; }
.verify-row button { border:1px solid var(--line); border-radius:999px; padding:8px 14px; cursor:pointer; font:inherit; }
#verify-entity { background:#12382f; border-color:#1f6b58; color:var(--ink); }
#reject-entity { background:#3a1d24; border-color:#7a3b48; color:var(--warn); }
ul { margin:0; padding-left:0; list-style:none; color:var(--muted); }
li { margin:6px 0; display:flex; align-items:center; gap:8px; }
ul[data-testid="graph-legend"] { display:flex; flex-wrap:wrap; gap:4px 14px; margin:8px 0 0; }
ul[data-testid="graph-legend"] li { margin:0; font-size:12px; }
#node-detail .lead { margin:10px 0 0; color:var(--ink); font-size:15px; line-height:1.4; }
.links { flex:1 1 auto; min-height:0; display:flex; flex-direction:column; }
.link-summary { margin:0 0 8px; color:var(--muted); font-size:13px; }
#relation-list { position:relative; flex:1 1 auto; min-height:0; overflow:auto; border:1px solid var(--line); border-radius:12px; background:#0b1020; }
.rel-row { display:flex; flex-wrap:wrap; align-items:center; align-content:center; gap:2px 8px; width:100%; text-align:left; border:0; border-bottom:1px solid #1d2740; background:transparent; color:var(--muted); padding:6px 10px; cursor:pointer; font:inherit; overflow:hidden; }
.rel-row .who { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ink); }
.rel-row .rel { flex:0 0 auto; color:var(--accent); font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; }
.rel-row .where { flex:1 1 100%; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:left; font-size:12px; padding-left:17px; }
.rel-row.selected { background:#152033; }
.rel-empty { margin:0; padding:14px; color:var(--muted); }
i[data-group] { display:inline-block; width:9px; height:9px; border-radius:99px; flex:0 0 auto; }
i[data-group="people"] { background:var(--accent); }
i[data-group="contact"] { background:var(--gold); }
i[data-group="locations"] { background:var(--blue); }
i[data-group="web"] { background:var(--violet); }
@media (max-width: 1100px) {
  header { flex-direction:column; align-items:flex-start; }
  .layout { grid-template-columns:1fr; height:auto; }
  #network { height:72vh; order:-1; }
  #relation-list { min-height:320px; }
  .panel { overflow:visible; }
}
"""


def render_report_html(graph, title: str) -> str:
    counts = _counts(graph)
    filters = []
    legend = []
    for key, label in _FILTERS:
        safe_key = html.escape(key, quote=True)
        safe_label = html.escape(label)
        count = counts[key]
        active = _filter_on(key, counts)
        state = " on" if active else ""
        pressed = "true" if active else "false"
        filters.append(
            f'<button type="button" class="filter{state}" data-testid="group-filter-{safe_key}" '
            f'data-category="{safe_key}" aria-pressed="{pressed}">{safe_label} <span>{count}</span></button>'
        )
        legend.append(f'<li data-group="{safe_key}"><i data-group="{safe_key}"></i>{safe_label} · {count}</li>')
    pages = sum(1 for node in graph.nodes if getattr(node, "type", "") == "DOMAIN")
    entities = len(graph.nodes) - pages
    safe_title = html.escape(title, quote=True)
    if _has_findings(counts):
        summary = _findings_blurb(counts)
        hint = "Click a lit group to focus it. Click the same group again to bring the other findings back."
    else:
        summary = "No people, phones, emails, or places were extracted. The map is showing the web footprint."
        hint = "People, contact points, and places show up here when a crawl extracts them."
    safe_summary = html.escape(summary)
    safe_hint = html.escape(hint)
    vendor = _safe_script(_VENDOR_PATH.read_text(encoding="utf-8"))
    app = _safe_script(_APP_PATH.read_text(encoding="utf-8"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
{_STYLE}
</style>
</head>
<body>
<header>
  <div>
    <p class="kicker">Findings</p>
    <h1 data-testid="report-title">{safe_title}</h1>
    <p class="sub">{safe_summary}</p>
  </div>
  <div class="stats" data-testid="report-stats">
    <div class="stat"><b>{pages}</b><span>Sources</span></div>
    <div class="stat"><b>{entities}</b><span>Entities</span></div>
    <div class="stat"><b>{len(graph.edges)}</b><span>Links</span></div>
  </div>
</header>
<div class="layout" data-testid="report-layout">
  <aside class="panel" data-testid="filter-pane">
    <label for="graph-search">Search</label>
    <input id="graph-search" data-testid="graph-search" type="search" aria-label="Search nodes" placeholder="Name, phone, email, place, source">
    <div class="filters" data-testid="graph-filters">{''.join(filters)}</div>
    <p id="view-hint" class="hint" data-testid="view-hint">{safe_hint}</p>
    <ul data-testid="graph-legend">{''.join(legend)}</ul>
    <div class="links">
      <h2>Connections</h2>
      <p id="link-summary" class="link-summary"></p>
      <div id="relation-list" data-testid="relation-list" data-windowed="1"></div>
    </div>
  </aside>
  <section id="network" data-testid="network" aria-label="Relationship network"></section>
  <aside class="panel" data-testid="inspector-pane">
    <h2>Inspector</h2>
    <div id="node-detail" data-testid="node-detail"><p class="meta">Select a person, phone, email, place, or source. This pane lists what it connects to.</p></div>
    <div class="verify-row">
      <button type="button" id="verify-entity" data-testid="verify-entity">Verify</button>
      <button type="button" id="reject-entity" data-testid="reject-entity">Reject</button>
    </div>
    <p id="verification-status" data-testid="verification-status">Unreviewed</p>
  </aside>
</div>
<script id="graph-data" type="application/json">{_payload(graph)}</script>
<script id="vendor-libs" data-vendor="dompurify zod zustand">{vendor}</script>
<script id="report-app">{app}</script>
</body>
</html>
"""
