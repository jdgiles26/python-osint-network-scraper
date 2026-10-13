"""Canonical entity graph built from scraped rows.

Identical normalized values share one node. Every entity edge lands on the
source domain that asserted it. Category filters use the adjacency index and
keep those source edges, so a phone view cannot show an isolated number.
"""
import ast
import json
from dataclasses import dataclass, field
from urllib.parse import urlparse

from src.domain.normalize import EntityType, process_record


PREDICATE_PHONE = "HAS_PHONE"
PREDICATE_ADDRESS = "RESIDED_AT"
PREDICATE_OTHER = "ASSOCIATED_WITH"

GROUP_BY_TYPE = {
    EntityType.PERSON: "people",
    EntityType.ORGANIZATION: "people",
    EntityType.PHONE: "contact",
    EntityType.EMAIL: "contact",
    EntityType.ADDRESS: "locations",
    EntityType.PROVENANCE: "web",
    "DOMAIN": "web",
}


@dataclass(frozen=True)
class GraphNode:
    id: str
    label: str
    group: str
    type: str = "PROVENANCE"
    value: str = ""
    confidence: float = 0.0
    source_domain: str = ""
    raw_metadata_key: str = ""
    observations: tuple = ()


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    id: str = ""

    def __post_init__(self):
        if not self.id:
            object.__setattr__(self, "id", f"{self.source}|{self.relation}|{self.target}")


@dataclass(frozen=True)
class RelationGraph:
    nodes: list
    edges: list
    index: dict = field(default_factory=dict)


def predicate_for(entity_type: str) -> str:
    if entity_type == EntityType.PHONE:
        return PREDICATE_PHONE
    if entity_type == EntityType.ADDRESS:
        return PREDICATE_ADDRESS
    return PREDICATE_OTHER


def source_domain(source: str) -> str:
    try:
        host = urlparse(source).hostname
    except Exception:
        host = None
    if not host:
        return source or ""
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def build_adjacency_index(edges) -> dict:
    """Bidirectional index: node id → edge ids, edge id → endpoint pair."""
    node_to_edges = {}
    edge_to_nodes = {}
    for edge in edges or []:
        edge_id = edge.id or f"{edge.source}|{edge.relation}|{edge.target}"
        edge_to_nodes[edge_id] = (edge.source, edge.target)
        node_to_edges.setdefault(edge.source, set()).add(edge_id)
        node_to_edges.setdefault(edge.target, set()).add(edge_id)
    return {"nodeToEdges": node_to_edges, "edgeToNodes": edge_to_nodes}


def _parse_entities(raw):
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _values(raw):
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str) and item]
    return []


def _assertions(entities):
    for key, raw_values in entities.items():
        values = _values(raw_values)
        if str(key) == "metadata":
            for item in values:
                label, separator, value = item.partition(": ")
                if separator and value:
                    yield label, value
                else:
                    yield str(key), item
            continue
        for value in values:
            yield str(key), value


def _node_from_record(record, observations):
    domains = []
    keys = []
    for item in observations:
        if item["sourceDomain"] not in domains:
            domains.append(item["sourceDomain"])
        if item["rawMetadataKey"] and item["rawMetadataKey"] not in keys:
            keys.append(item["rawMetadataKey"])
    confidence = max(item["confidence"] for item in observations)
    return GraphNode(
        id=record.id,
        label=record.value,
        group=GROUP_BY_TYPE.get(record.type, "web"),
        type=record.type,
        value=record.value,
        confidence=confidence,
        source_domain=", ".join(domains),
        raw_metadata_key=", ".join(keys),
        observations=tuple(observations),
    )


def build_relation_graph(rows):
    records = {}
    observations = {}
    edge_map = {}
    domains = {}

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        source = row.get("SourceURL") or ""
        if not source:
            continue
        domain = source_domain(source)
        if not domain:
            continue
        entities = _parse_entities(row.get("Entities"))
        if not isinstance(entities, dict):
            continue
        for key, raw_value in _assertions(entities):
            record = process_record(domain, key, raw_value)
            if record is None:
                continue
            if record.id not in records:
                records[record.id] = record
            observation = {
                "sourceDomain": domain,
                "rawMetadataKey": record.raw_metadata_key,
                "confidence": record.confidence,
            }
            bucket = observations.setdefault(record.id, [])
            if observation not in bucket:
                bucket.append(observation)
            domain_id = f"DOMAIN:{domain}"
            domains[domain_id] = domain
            relation = predicate_for(record.type)
            edge_id = f"{domain_id}|{relation}|{record.id}"
            edge_map[edge_id] = GraphEdge(domain_id, record.id, relation, edge_id)

    nodes = []
    for domain_id, domain in domains.items():
        nodes.append(GraphNode(
            id=domain_id,
            label=domain,
            group="web",
            type="DOMAIN",
            value=domain,
            confidence=1.0,
            source_domain=domain,
            raw_metadata_key="",
            observations=(),
        ))
    for record_id, record in records.items():
        nodes.append(_node_from_record(record, observations.get(record_id) or [{
            "sourceDomain": record.source_domain,
            "rawMetadataKey": record.raw_metadata_key,
            "confidence": record.confidence,
        }]))
    edges = list(edge_map.values())
    return RelationGraph(nodes, edges, build_adjacency_index(edges))


def _query_match(node, query: str) -> bool:
    if not query:
        return True
    haystack = " ".join((
        node.label or "",
        node.value or "",
        node.id or "",
        node.source_domain or "",
        node.raw_metadata_key or "",
    )).lower()
    return query.lower() in haystack


def _category_match(node, category) -> bool:
    if node.type == "DOMAIN":
        return False
    if not category:
        return True
    token = str(category).strip().lower()
    if token in {"phone", "phones"}:
        return node.type == EntityType.PHONE
    if token in {"email", "emails"}:
        return node.type == EntityType.EMAIL
    if token in {"people", "person", "persons"}:
        return node.type in {EntityType.PERSON, EntityType.ORGANIZATION}
    if token in {"contact", "contacts", "contact points"}:
        return node.type in {EntityType.PHONE, EntityType.EMAIL}
    if token in {"locations", "location", "address", "addresses"}:
        return node.type == EntityType.ADDRESS
    if token in {"web", "web footprint", "provenance"}:
        return node.type == EntityType.PROVENANCE
    return node.group == token or node.type == str(category).upper()


def filter_relation_graph(graph, category=None, query=""):
    """Return the category view. Every visible entity keeps a source edge."""
    if graph is None:
        return RelationGraph([], [], build_adjacency_index([]))
    index = graph.index or build_adjacency_index(graph.edges)
    node_to_edges = index.get("nodeToEdges") or {}
    edge_to_nodes = index.get("edgeToNodes") or {}
    nodes_by_id = {node.id: node for node in graph.nodes}
    edges_by_id = {edge.id: edge for edge in graph.edges}

    selected = []
    seen_ids = set()
    for node in graph.nodes:
        if not _category_match(node, category) or not _query_match(node, query):
            continue
        if node.id not in seen_ids:
            selected.append(node)
            seen_ids.add(node.id)

    if query:
        needle = query.lower()
        for node in graph.nodes:
            if node.type != "DOMAIN" or needle not in (node.label or "").lower():
                continue
            for edge_id in node_to_edges.get(node.id, ()):
                ends = edge_to_nodes.get(edge_id)
                if not ends:
                    continue
                other_id = ends[1] if ends[0] == node.id else ends[0]
                other = nodes_by_id.get(other_id)
                if other and other.id not in seen_ids and _category_match(other, category):
                    selected.append(other)
                    seen_ids.add(other.id)

    kept_nodes = {}
    kept_edge_ids = []
    seen_edges = set()
    for node in selected:
        kept_nodes[node.id] = node
        for edge_id in node_to_edges.get(node.id, ()):
            if edge_id in seen_edges or edge_id not in edges_by_id:
                continue
            ends = edge_to_nodes.get(edge_id)
            if not ends:
                continue
            other_id = ends[1] if ends[0] == node.id else ends[0]
            other = nodes_by_id.get(other_id)
            if other is None:
                continue
            kept_nodes[other.id] = other
            seen_edges.add(edge_id)
            kept_edge_ids.append(edge_id)

    edges = [edges_by_id[edge_id] for edge_id in kept_edge_ids]
    # Drop anything that lost its edge. Domains arrive only as edge endpoints.
    linked = set()
    for edge in edges:
        linked.add(edge.source)
        linked.add(edge.target)
    nodes = [node for node in kept_nodes.values() if node.id in linked]
    return RelationGraph(nodes, edges, build_adjacency_index(edges))
