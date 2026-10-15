(function () {
  "use strict";

  const rawText = document.getElementById("graph-data").textContent;
  const raw = JSON.parse(rawText);
  const PayloadSchema = z.object({
    nodes: z.array(z.object({
      id: z.string(),
      label: z.string(),
      group: z.string(),
      type: z.enum(["PERSON", "PHONE", "EMAIL", "ADDRESS", "ORGANIZATION", "PROVENANCE", "DOMAIN"]),
      value: z.string(),
      confidence: z.number(),
      sourceDomain: z.string(),
      rawMetadataKey: z.string(),
      observations: z.array(z.object({
        sourceDomain: z.string(),
        rawMetadataKey: z.string(),
        confidence: z.number()
      }))
    })),
    edges: z.array(z.object({
      id: z.string(),
      source: z.string(),
      target: z.string(),
      predicate: z.string()
    }))
  });
  const parsed = PayloadSchema.safeParse(raw);
  const host = document.getElementById("network");
  if (!parsed.success) {
    window.__ZOD_OK__ = false;
    host.textContent = "The report payload failed validation.";
    return;
  }
  window.__ZOD_OK__ = true;
  const records = parsed.data;

  function safeText(value) {
    const original = value == null ? "" : String(value);
    if (!globalThis.DOMPurify || typeof globalThis.DOMPurify.sanitize !== "function") {
      return original.replace(/[<>]/g, "");
    }
    const clean = globalThis.DOMPurify.sanitize(original, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
    window.__DOM_PURIFY_USED__ = true;
    return clean == null ? "" : String(clean);
  }

  function prettyPhone(text) {
    const digits = String(text || "").replace(/\D/g, "");
    let body = "";
    if (digits.length === 11 && digits.charAt(0) === "1") body = digits.slice(1);
    else if (digits.length === 10) body = digits;
    if (body.length !== 10) return String(text || "");
    return "+1 " + body.slice(0, 3) + " " + body.slice(3, 6) + " " + body.slice(6);
  }

  function prettyLabel(node) {
    const raw = safeText((node && (node.label || node.value || node.id)) || "");
    if (node && node.type === "PHONE") return prettyPhone(raw);
    return raw;
  }

  function displayNode(node) {
    return {
      id: node.id,
      label: prettyLabel(node),
      group: node.group,
      type: node.type,
      value: safeText(node.value),
      confidence: node.confidence,
      sourceDomain: safeText(node.sourceDomain),
      rawMetadataKey: safeText(node.rawMetadataKey),
      observations: (node.observations || []).map(function (item) {
        return {
          sourceDomain: safeText(item.sourceDomain),
          rawMetadataKey: safeText(item.rawMetadataKey),
          confidence: item.confidence
        };
      })
    };
  }

  function buildIndex(edges) {
    const nodeToEdges = new Map();
    const edgeToNodes = new Map();
    edges.forEach(function (edge) {
      edgeToNodes.set(edge.id, [edge.source, edge.target]);
      [edge.source, edge.target].forEach(function (end) {
        if (!nodeToEdges.has(end)) nodeToEdges.set(end, new Set());
        nodeToEdges.get(end).add(edge.id);
      });
    });
    return { nodeToEdges: nodeToEdges, edgeToNodes: edgeToNodes };
  }

  const index = buildIndex(records.edges);
  window.__GRAPH_INDEX__ = {
    nodeToEdges: index.nodeToEdges,
    edgeToNodes: index.edgeToNodes
  };
  const nodesById = new Map(records.nodes.map(function (node) { return [node.id, node]; }));
  const edgesById = new Map(records.edges.map(function (edge) { return [edge.id, edge]; }));
  const graph = { nodes: records.nodes, nodesById: nodesById, edgesById: edgesById };

  function categoryMatch(node, enabled) {
    if (!node || node.type === "DOMAIN") return false;
    return !!enabled[node.group];
  }

  function queryMatch(node, query) {
    if (!query) return true;
    const hay = [node.label, node.value, node.id, node.sourceDomain, node.rawMetadataKey].join(" ").toLowerCase();
    return hay.indexOf(query) !== -1;
  }

  function computeVisible(state) {
    const enabled = state.enabled;
    const query = (state.query || "").trim().toLowerCase();
    const selected = [];
    const seen = new Set();
    graph.nodes.forEach(function (node) {
      if (!categoryMatch(node, enabled) || !queryMatch(node, query)) return;
      if (seen.has(node.id)) return;
      seen.add(node.id);
      selected.push(node);
    });
    if (query) {
      graph.nodes.forEach(function (node) {
        if (node.type !== "DOMAIN" || String(node.label || "").toLowerCase().indexOf(query) === -1) return;
        const edgeIds = index.nodeToEdges.get(node.id);
        if (!edgeIds) return;
        edgeIds.forEach(function (edgeId) {
          const ends = index.edgeToNodes.get(edgeId);
          if (!ends) return;
          const otherId = ends[0] === node.id ? ends[1] : ends[0];
          const other = nodesById.get(otherId);
          if (!other || seen.has(other.id) || !categoryMatch(other, enabled)) return;
          seen.add(other.id);
          selected.push(other);
        });
      });
    }
    const kept = new Map();
    const edges = [];
    const seenEdges = new Set();
    selected.forEach(function (node) {
      kept.set(node.id, node);
      const edgeIds = index.nodeToEdges.get(node.id);
      if (!edgeIds) return;
      edgeIds.forEach(function (edgeId) {
        if (seenEdges.has(edgeId)) return;
        const edge = edgesById.get(edgeId);
        const ends = index.edgeToNodes.get(edgeId);
        if (!edge || !ends) return;
        const otherId = ends[0] === node.id ? ends[1] : ends[0];
        const other = nodesById.get(otherId);
        if (!other) return;
        kept.set(other.id, other);
        seenEdges.add(edgeId);
        edges.push(edge);
      });
    });
    const linked = new Set();
    edges.forEach(function (edge) {
      linked.add(edge.source);
      linked.add(edge.target);
    });
    const nodes = [];
    kept.forEach(function (node) {
      if (linked.has(node.id)) nodes.push(displayNode(node));
    });
    return { nodes: nodes, edges: edges };
  }

  function incidentArray(selectedId) {
    if (!selectedId) return null;
    const edgeIds = index.nodeToEdges.get(selectedId);
    return edgeIds ? Array.from(edgeIds) : [];
  }

  const CATEGORIES = ["people", "contact", "locations", "web"];
  const TYPE_NAME = {
    PERSON: "Person",
    ORGANIZATION: "Organization",
    PHONE: "Phone",
    EMAIL: "Email",
    ADDRESS: "Place",
    PROVENANCE: "Page detail",
    DOMAIN: "Source"
  };
  const PHRASE = {
    PERSON: "named on",
    ORGANIZATION: "organization on",
    PHONE: "phone on",
    EMAIL: "email on",
    ADDRESS: "place on",
    PROVENANCE: "detail on"
  };

  function cloneEnabled(source) {
    return {
      people: !!source.people,
      contact: !!source.contact,
      locations: !!source.locations,
      web: !!source.web
    };
  }

  function sameEnabled(left, right) {
    return CATEGORIES.every(function (key) { return !!left[key] === !!right[key]; });
  }

  function enabledFromDom() {
    const enabled = { people: true, contact: true, locations: true, web: false };
    const buttons = document.querySelectorAll("button.filter");
    if (!buttons.length) return enabled;
    buttons.forEach(function (button) {
      const category = button.getAttribute("data-category");
      if (CATEGORIES.indexOf(category) === -1) return;
      enabled[category] = button.classList.contains("on");
    });
    if (!CATEGORIES.some(function (key) { return enabled[key]; })) {
      return { people: true, contact: true, locations: true, web: false };
    }
    return enabled;
  }

  const DEFAULT_ENABLED = enabledFromDom();

  function publish(set, data) {
    const visible = computeVisible(data);
    let selectedId = data.selectedId;
    if (selectedId && !visible.nodes.some(function (node) { return node.id === selectedId; })) {
      selectedId = "";
    }
    set({
      query: data.query,
      enabled: data.enabled,
      selectedId: selectedId,
      status: data.status,
      visibleNodes: visible.nodes,
      visibleEdges: visible.edges,
      drawToken: (data.drawToken || 0) + 1
    });
  }

  const store = createStore(function (set, get) {
    return {
      query: "",
      enabled: cloneEnabled(DEFAULT_ENABLED),
      selectedId: "",
      status: {},
      visibleNodes: [],
      visibleEdges: [],
      positions: {},
      drawToken: 0,
      setQuery: function (query) {
        const current = get();
        publish(set, {
          query: query,
          enabled: current.enabled,
          selectedId: current.selectedId,
          status: current.status,
          drawToken: current.drawToken
        });
      },
      toggleCategory: function (category) {
        const current = get();
        if (CATEGORIES.indexOf(category) === -1) return;
        const active = CATEGORIES.filter(function (key) { return current.enabled[key]; });
        let enabled;
        if (sameEnabled(current.enabled, DEFAULT_ENABLED)) {
          if (current.enabled[category]) {
            enabled = { people: false, contact: false, locations: false, web: false };
            enabled[category] = true;
          } else {
            enabled = cloneEnabled(current.enabled);
            enabled[category] = true;
          }
        } else if (active.length === 1 && active[0] === category) {
          enabled = cloneEnabled(DEFAULT_ENABLED);
        } else {
          enabled = cloneEnabled(current.enabled);
          enabled[category] = !enabled[category];
          if (!CATEGORIES.some(function (key) { return enabled[key]; })) enabled = cloneEnabled(DEFAULT_ENABLED);
        }
        publish(set, {
          query: current.query,
          enabled: enabled,
          selectedId: current.selectedId,
          status: current.status,
          drawToken: current.drawToken
        });
      },
      select: function (id) {
        const current = get();
        const enabled = cloneEnabled(current.enabled);
        const node = id ? nodesById.get(id) : null;
        if (node && node.type !== "DOMAIN" && CATEGORIES.indexOf(node.group) !== -1) {
          enabled[node.group] = true;
        }
        publish(set, {
          query: current.query,
          enabled: enabled,
          selectedId: id || "",
          status: current.status,
          drawToken: current.drawToken
        });
      },
      setStatus: function (id, value) {
        const current = get();
        const status = Object.assign({}, current.status);
        status[id] = value;
        publish(set, {
          query: current.query,
          enabled: current.enabled,
          selectedId: current.selectedId,
          status: status,
          drawToken: current.drawToken
        });
      },
      setPositions: function (positions) {
        set({ positions: positions });
      }
    };
  });
  window.__REPORT_STORE__ = store;

  const WORKER_SOURCE = `
"use strict";
let surface = null;
let ctx = null;
function byReadingOrder(a, b) {
  const rank = { PERSON: 0, ORGANIZATION: 1, PHONE: 2, EMAIL: 3, ADDRESS: 4, PROVENANCE: 5, DOMAIN: 6 };
  const ra = rank[a.type] == null ? 9 : rank[a.type];
  const rb = rank[b.type] == null ? 9 : rank[b.type];
  if (ra !== rb) return ra - rb;
  const la = String(a.label || "").toLowerCase();
  const lb = String(b.label || "").toLowerCase();
  if (la < lb) return -1;
  if (la > lb) return 1;
  return 0;
}
function layoutGraph(nodes, edges, width, height) {
  const positions = {};
  const cells = [];
  const byId = {};
  const domains = [];
  const entities = [];
  (nodes || []).forEach(function (node) {
    if (!node || !node.id) return;
    byId[node.id] = node;
    if (node.type === "DOMAIN") domains.push(node);
    else entities.push(node);
  });
  domains.sort(byReadingOrder);
  const homes = {};
  entities.forEach(function (node) { homes[node.id] = []; });
  (edges || []).forEach(function (edge) {
    const source = byId[edge.source];
    const target = byId[edge.target];
    if (!source || !target) return;
    const domain = source.type === "DOMAIN" ? source : (target.type === "DOMAIN" ? target : null);
    const entity = source.type === "DOMAIN" ? target : (target.type === "DOMAIN" ? source : null);
    if (!domain || !entity || entity.type === "DOMAIN" || !homes[entity.id]) return;
    if (homes[entity.id].indexOf(domain.id) === -1) homes[entity.id].push(domain.id);
  });
  const lanes = {};
  domains.forEach(function (domain) { lanes[domain.id] = []; });
  const orphans = [];
  entities.forEach(function (node) {
    const home = (homes[node.id] || [])[0];
    if (home && lanes[home]) lanes[home].push(node);
    else orphans.push(node);
  });
  Object.keys(lanes).forEach(function (id) { lanes[id].sort(byReadingOrder); });
  orphans.sort(byReadingOrder);
  const laneIds = domains.map(function (domain) { return domain.id; });
  if (orphans.length) {
    laneIds.push("__other__");
    lanes.__other__ = orphans;
  }
  laneIds.sort(function (a, b) {
    return (lanes[b] || []).length - (lanes[a] || []).length;
  });
  const margin = 16;
  const headerBlock = 26;
  const laneGap = 8;
  const usableH = Math.max(140, height - margin * 2);
  const usableW = Math.max(160, width - margin * 2);
  const memberCount = entities.length;
  const headerCount = Math.max(1, laneIds.length);
  const oneColFree = usableH - headerCount * headerBlock - headerCount * laneGap;
  let columns = 1;
  if (laneIds.length > 1 && oneColFree / Math.max(1, memberCount) < 22) columns = 2;
  if (laneIds.length > 2 && oneColFree / Math.max(1, memberCount) < 12) columns = 3;
  const maxByWidth = Math.max(1, Math.floor(usableW / 240));
  columns = Math.min(columns, maxByWidth, laneIds.length || 1);
  const cols = [];
  for (let i = 0; i < columns; i += 1) cols.push([]);
  function laneWeight(ids) {
    return ids.reduce(function (sum, id) { return sum + (lanes[id] || []).length; }, 0);
  }
  laneIds.forEach(function (id) {
    let best = 0;
    for (let i = 1; i < cols.length; i += 1) {
      if (laneWeight(cols[i]) < laneWeight(cols[best])) best = i;
    }
    cols[best].push(id);
  });
  const colW = usableW / columns;
  cols.forEach(function (ids, colIndex) {
    if (!ids.length) return;
    const members = laneWeight(ids);
    const free = usableH - ids.length * headerBlock - ids.length * laneGap;
    const pitch = Math.max(15, Math.min(28, free / Math.max(1, members)));
    let y = margin;
    const x0 = margin + colW * colIndex;
    ids.forEach(function (id, laneIndex) {
      const group = lanes[id] || [];
      const band = headerBlock + group.length * pitch;
      cells.push({
        x: x0,
        y: y,
        w: Math.max(8, colW - 10),
        h: band,
        title: "",
        fill: laneIndex % 2 ? "#121c2e" : "#17263a"
      });
      const laneKey = id;
      if (id !== "__other__") {
        positions[id] = {
          x: x0 + 14,
          y: y + 14,
          labelMax: Math.max(48, colW - 52),
          pitch: pitch,
          lane: laneKey
        };
      }
      group.forEach(function (node, offset) {
        const sourceCount = (homes[node.id] || []).length;
        positions[node.id] = {
          x: x0 + 26,
          y: y + headerBlock + pitch * (offset + 0.5),
          labelMax: Math.max(48, colW - 62),
          pitch: pitch,
          lane: laneKey,
          extraSources: sourceCount > 1 ? sourceCount : 0
        };
      });
      y += band + laneGap;
    });
  });
  let neededHeight = margin;
  cells.forEach(function (cell) { neededHeight = Math.max(neededHeight, cell.y + cell.h + margin); });
  return { positions: positions, cells: cells, neededHeight: neededHeight };
}
function roundRect(context, x, y, w, h, r) {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  context.beginPath();
  context.moveTo(x + radius, y);
  context.arcTo(x + w, y, x + w, y + h, radius);
  context.arcTo(x + w, y + h, x, y + h, radius);
  context.arcTo(x, y + h, x, y, radius);
  context.arcTo(x, y, x + w, y, radius);
  context.closePath();
}
const NODE_COLOR = { PERSON: "#6ee7d2", ORGANIZATION: "#5eead4", PHONE: "#f0c05a", EMAIL: "#86efac", ADDRESS: "#8eb6ff", PROVENANCE: "#c084fc", DOMAIN: "#a5b4fc" };
function paintGraph(message) {
  const width = message.width;
  let height = message.height;
  const nodes = message.nodes || [];
  const laid = nodes.length
    ? layoutGraph(nodes, message.edges || [], width, height)
    : { positions: {}, cells: [], neededHeight: height };
  height = Math.max(height, laid.neededHeight || 0);
  surface.width = width;
  surface.height = height;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#101828";
  ctx.fillRect(0, 0, width, height);
  if (!nodes.length) {
    ctx.fillStyle = "#93a0bd";
    ctx.font = "16px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("Nothing in this view. Turn on another group.", width / 2, height / 2);
    return { positions: {}, height: height };
  }
  laid.cells.forEach(function (cell) {
    ctx.globalAlpha = 1;
    ctx.fillStyle = cell.fill || "#182236";
    roundRect(ctx, cell.x, cell.y, cell.w, cell.h, 14);
    ctx.fill();
    if (!cell.title) return;
    ctx.fillStyle = cell.swatch || "#6ee7d2";
    ctx.fillRect(cell.x + 12, cell.y + 12, 8, 8);
    ctx.fillStyle = "#c5d2ea";
    ctx.font = "13px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(cell.title, cell.x + 26, cell.y + 8);
  });
  const typeById = {};
  nodes.forEach(function (node) { typeById[node.id] = node.type; });
  const focused = !!message.selectedId;
  const incident = message.incidentIds;
  const neighbor = {};
  if (message.selectedId) neighbor[message.selectedId] = true;
  (message.edges || []).forEach(function (edge) {
    const a = laid.positions[edge.source];
    const b = laid.positions[edge.target];
    if (!a || !b) return;
    const hot = !!(focused && incident && incident.indexOf(edge.id) !== -1);
    if (hot) { neighbor[edge.source] = true; neighbor[edge.target] = true; }
    const local = !!(a.lane && a.lane === b.lane);
    if (!local && !hot) return;
    let kind = typeById[edge.target];
    if (kind === "DOMAIN") kind = typeById[edge.source];
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    if (hot) {
      ctx.globalAlpha = 0.95;
      ctx.lineWidth = 2.2;
      ctx.strokeStyle = NODE_COLOR[kind] || "#b7f3e4";
    } else if (!focused) {
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = NODE_COLOR[kind] || "#8ea0c4";
    } else {
      ctx.globalAlpha = 0.16;
      ctx.lineWidth = 1;
      ctx.strokeStyle = "#31415f";
    }
    ctx.stroke();
  });
  function fitLabel(text, maxWidth) {
    let value = String(text || "");
    if (ctx.measureText(value).width <= maxWidth) return value;
    while (value.length > 1 && ctx.measureText(value + "…").width > maxWidth) value = value.slice(0, -1);
    return value + "…";
  }
  nodes.forEach(function (node) {
    const pos = laid.positions[node.id];
    if (!pos) return;
    const dim = !!(focused && !neighbor[node.id]);
    const selected = node.id === message.selectedId;
    const hot = !!neighbor[node.id];
    const provenance = node.type === "PROVENANCE";
    ctx.globalAlpha = dim ? 0.55 : 1;
    ctx.fillStyle = NODE_COLOR[node.type] || "#d6def2";
    ctx.beginPath();
    const radius = selected ? 8 : (provenance ? 3.5 : (node.type === "DOMAIN" ? 6 : 5.5));
    ctx.arc(pos.x, pos.y, radius, 0, Math.PI * 2);
    ctx.fill();
    const labelOk = (!provenance || hot || (pos.pitch || 0) >= 18) && ((pos.labelMax || 0) >= 28 || hot);
    if (!labelOk) return;
    ctx.font = (selected ? "700 " : "") + "13px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    let badge = "";
    if (pos.extraSources > 1) badge = " · " + pos.extraSources + " sources";
    const maxWidth = Math.max(28, pos.labelMax || 120);
    const nameWidth = Math.max(28, maxWidth - (badge ? ctx.measureText(badge).width : 0));
    const text = fitLabel(node.label, nameWidth) + badge;
    const lx = pos.x + radius + 8;
    const ly = pos.y;
    ctx.lineWidth = 4;
    ctx.strokeStyle = "rgba(16,24,40,0.88)";
    ctx.strokeText(text, lx, ly);
    ctx.fillStyle = dim ? "#9aabc8" : (NODE_COLOR[node.type] || "#f8fbff");
    ctx.fillText(text, lx, ly);
  });
  ctx.globalAlpha = 1;
  return { positions: laid.positions, height: Math.max(height, laid.neededHeight || height) };
}
self.onmessage = function (event) {
  const message = event.data || {};
  if (message.canvas) { surface = message.canvas; ctx = surface.getContext("2d"); }
  if (!surface || !ctx) return;
  const width = Math.max(1, message.width | 0);
  const height = Math.max(1, message.height | 0);
  const painted = paintGraph({ nodes: message.nodes, edges: message.edges, width: width, height: height, selectedId: message.selectedId || "", incidentIds: message.incidentIds || null });
  self.postMessage({ type: "painted", positions: painted.positions || {}, width: width, height: painted.height || height });
};
`;


  const canvas = document.createElement("canvas");
  canvas.setAttribute("data-testid", "graph-canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Entity graph");
  host.appendChild(canvas);

  let worker = null;
  let ready = false;
  let pending = null;
  let lastDraw = -1;
  let lastSize = { width: 0, height: 0 };

  function measure() {
    const rect = host.getBoundingClientRect();
    return {
      width: Math.max(1, Math.round(rect.width)),
      height: Math.max(1, Math.round(rect.height))
    };
  }

  function drawMessage(state, size) {
    const incidentIds = incidentArray(state.selectedId);
    const visibleIds = new Set(state.visibleEdges.map(function (edge) { return edge.id; }));
    const dimmed = !!state.selectedId && state.visibleEdges.some(function (edge) {
      return !incidentIds || incidentIds.indexOf(edge.id) === -1;
    });
    window.__PATHS_DIMMED__ = dimmed;
    window.__LAST_DRAW__ = {
      selectedId: state.selectedId,
      incidentIds: incidentIds,
      edgeCount: state.visibleEdges.length,
      nodeCount: state.visibleNodes.length,
      dimmed: dimmed,
      visibleEdgeIds: Array.from(visibleIds)
    };
    return {
      type: "draw",
      nodes: state.visibleNodes,
      edges: state.visibleEdges,
      width: size.width,
      height: size.height,
      selectedId: state.selectedId,
      incidentIds: incidentIds
    };
  }

  function postDraw(state) {
    const size = measure();
    lastSize = size;
    const message = drawMessage(state, size);
    if (!ready || !worker) {
      pending = message;
      return;
    }
    worker.postMessage(message);
  }

  const search = document.getElementById("graph-search");
  const listHost = document.getElementById("relation-list");
  const detail = document.getElementById("node-detail");
  const statusEl = document.getElementById("verification-status");
  const ROW_HEIGHT = 62;

  function rankType(type) {
    const rank = { PERSON: 0, ORGANIZATION: 1, PHONE: 2, EMAIL: 3, ADDRESS: 4, DOMAIN: 5, PROVENANCE: 6 };
    return rank[type] == null ? 9 : rank[type];
  }

  function isFinding(node) {
    return !!node && (node.type === "PERSON" || node.type === "ORGANIZATION" || node.type === "PHONE" || node.type === "EMAIL" || node.type === "ADDRESS");
  }

  function confidenceLabel(value) {
    const n = Number(value);
    if (!isFinite(n)) return "—";
    const pct = Math.round(n * 100);
    const band = n >= 0.9 ? "High" : (n >= 0.75 ? "Medium" : "Low");
    return band + " · " + pct + "%";
  }

  function nodeLookup(state) {
    return new Map(state.visibleNodes.map(function (node) { return [node.id, node]; }));
  }

  function edgeParts(edge, lookup) {
    const source = lookup.get(edge.source);
    const target = lookup.get(edge.target);
    const targetIsEntity = target && target.type !== "DOMAIN";
    const entity = targetIsEntity ? target : source;
    const origin = targetIsEntity ? source : target;
    const type = entity ? entity.type : "";
    return {
      entity: entity,
      origin: origin,
      phrase: PHRASE[type] || "linked to",
      entityId: entity ? entity.id : edge.target
    };
  }

  function compareEdges(a, b, lookup) {
    const left = edgeParts(a, lookup);
    const right = edgeParts(b, lookup);
    const rank = rankType(left.entity && left.entity.type) - rankType(right.entity && right.entity.type);
    if (rank) return rank;
    const leftLabel = String(left.entity ? left.entity.label : a.target).toLowerCase();
    const rightLabel = String(right.entity ? right.entity.label : b.target).toLowerCase();
    if (leftLabel < rightLabel) return -1;
    if (leftLabel > rightLabel) return 1;
    const leftWhere = String(left.origin ? left.origin.label : "").toLowerCase();
    const rightWhere = String(right.origin ? right.origin.label : "").toLowerCase();
    if (leftWhere < rightWhere) return -1;
    if (leftWhere > rightWhere) return 1;
    return 0;
  }

  function orderedEdges(state) {
    const lookup = nodeLookup(state);
    return state.visibleEdges.slice().sort(function (a, b) { return compareEdges(a, b, lookup); });
  }

  function renderFilters(state) {
    document.querySelectorAll("button.filter").forEach(function (button) {
      const category = button.getAttribute("data-category");
      const on = !!state.enabled[category];
      button.classList.toggle("on", on);
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function renderHint(state) {
    const hint = document.getElementById("view-hint");
    if (!hint) return;
    const active = CATEGORIES.filter(function (key) { return state.enabled[key]; });
    const names = { people: "people", contact: "contact points", locations: "places", web: "the web footprint" };
    if (active.length === 1) {
      hint.textContent = "Focused on " + (names[active[0]] || active[0]) + ". Click that group again to bring the findings view back.";
      return;
    }
    if (state.enabled.web && (state.enabled.people || state.enabled.contact || state.enabled.locations)) {
      hint.textContent = "Web footprint is on, so page details are mixed in with the findings.";
      return;
    }
    if (state.enabled.web) {
      hint.textContent = "Showing the web footprint. These are page details such as site names.";
      return;
    }
    const shown = [];
    if (state.enabled.people) shown.push("people");
    if (state.enabled.contact) shown.push("contact points");
    if (state.enabled.locations) shown.push("places");
    hint.textContent = "Showing " + (shown.join(", ") || "findings") + ". Click a lit group to focus it.";
  }

  function findingRows(state) {
    const lookup = nodeLookup(state);
    const rows = [];
    const byId = new Map();
    orderedEdges(state).forEach(function (edge) {
      const parts = edgeParts(edge, lookup);
      const id = parts.entityId || edge.id;
      let row = byId.get(id);
      if (!row) {
        row = { entity: parts.entity, entityId: id, phrase: parts.phrase, origins: [] };
        byId.set(id, row);
        rows.push(row);
      }
      const origin = parts.origin;
      const originId = origin ? origin.id : "";
      const originLabel = origin ? origin.label : "";
      const seen = row.origins.some(function (item) { return item.id === originId; });
      if (!seen) row.origins.push({ id: originId, label: originLabel });
    });
    return rows;
  }

  function rowHits(row, selectedId) {
    if (!selectedId || !row) return false;
    if (row.entityId === selectedId) return true;
    return row.origins.some(function (origin) { return origin.id === selectedId; });
  }

  function whereText(row) {
    const labels = row.origins.map(function (origin) { return origin.label; }).filter(Boolean);
    if (labels.length <= 1) return labels[0] || "";
    if (labels.length === 2) return labels[0] + " · " + labels[1];
    return labels[0] + " · " + (labels.length - 1) + " more";
  }

  function renderSummary(state, rows) {
    const el = document.getElementById("link-summary");
    if (!el) return;
    const present = {};
    state.visibleNodes.forEach(function (node) {
      if (node.type !== "DOMAIN") present[node.group] = true;
    });
    const names = [];
    if (present.people) names.push("people");
    if (present.contact) names.push("contact points");
    if (present.locations) names.push("places");
    if (present.web) names.push("page details");
    const count = rows.length;
    let text = count + " finding" + (count === 1 ? "" : "s");
    let shared = 0;
    rows.forEach(function (row) { if (row.origins.length > 1) shared += 1; });
    if (shared) text += " · " + shared + " on more than one source";
    if (names.length) text += " · " + names.join(", ");
    let hidden = 0;
    records.nodes.forEach(function (node) {
      if (node.type === "PROVENANCE" && !state.enabled.web) hidden += 1;
    });
    if (hidden) text += " · " + hidden + " page details hidden";
    el.textContent = text;
  }

  function renderList(state) {
    const findings = findingRows(state);
    renderSummary(state, findings);
    let spacer = listHost.querySelector("[data-spacer]");
    if (!spacer) {
      spacer = document.createElement("div");
      spacer.setAttribute("data-spacer", "1");
      listHost.appendChild(spacer);
    }
    spacer.style.position = "relative";
    if (!findings.length) {
      spacer.style.height = "auto";
      const empty = document.createElement("p");
      empty.className = "rel-empty";
      empty.textContent = "No connections in this view.";
      spacer.replaceChildren(empty);
      return;
    }
    spacer.style.height = (findings.length * ROW_HEIGHT) + "px";
    const viewHeight = Math.max(listHost.clientHeight || 0, 280);
    const start = Math.max(0, Math.floor((listHost.scrollTop || 0) / ROW_HEIGHT));
    const count = Math.ceil(viewHeight / ROW_HEIGHT) + 2;
    const slice = findings.slice(start, start + count);
    const rows = document.createDocumentFragment();
    slice.forEach(function (item, offset) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "rel-row";
      row.style.position = "absolute";
      row.style.top = ((start + offset) * ROW_HEIGHT) + "px";
      row.style.height = ROW_HEIGHT + "px";
      row.style.left = "0";
      row.style.right = "0";
      if (rowHits(item, state.selectedId)) row.classList.add("selected");
      const whoText = item.entity ? item.entity.label : (item.entityId || "");
      const place = whereText(item);
      const phraseText = item.origins.length > 1 ? (item.origins.length + " sources") : (item.phrase || "linked to");
      const mark = document.createElement("i");
      mark.setAttribute("data-group", (item.entity && item.entity.group) || "web");
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = whoText;
      const phrase = document.createElement("span");
      phrase.className = "rel";
      phrase.textContent = phraseText;
      const where = document.createElement("span");
      where.className = "where";
      where.textContent = place;
      row.appendChild(mark);
      row.appendChild(who);
      row.appendChild(phrase);
      row.appendChild(where);
      const named = item.origins.map(function (origin) { return origin.label; }).filter(Boolean).join(" and ");
      const sentence = whoText + " " + (item.phrase || "linked to") + " " + named;
      row.setAttribute("aria-label", sentence);
      row.title = sentence;
      row.addEventListener("click", function () {
        store.getState().select(item.entityId);
      });
      rows.appendChild(row);
    });
    spacer.replaceChildren(rows);
  }

  function scrollSelection(state) {
    if (!state.selectedId) return;
    const findings = findingRows(state);
    let index = -1;
    for (let i = 0; i < findings.length; i += 1) {
      if (rowHits(findings[i], state.selectedId)) {
        index = i;
        break;
      }
    }
    if (index < 0) return;
    const top = index * ROW_HEIGHT;
    const view = listHost.clientHeight || 0;
    if (top < listHost.scrollTop || top + ROW_HEIGHT > listHost.scrollTop + view) {
      listHost.scrollTop = Math.max(0, top - ROW_HEIGHT);
    }
  }

  function addLine(parent, label, value) {
    const row = document.createElement("p");
    row.className = "meta";
    const name = document.createElement("b");
    name.textContent = label;
    row.appendChild(name);
    row.appendChild(document.createTextNode(" " + (value == null || value === "" ? "—" : value)));
    parent.appendChild(row);
  }

  function sectionTitle(text) {
    const heading = document.createElement("h3");
    heading.textContent = text;
    return heading;
  }

  function linkedNodes(nodeId) {
    const out = [];
    const seen = new Set();
    const edgeIds = index.nodeToEdges.get(nodeId);
    if (!edgeIds) return out;
    edgeIds.forEach(function (edgeId) {
      const ends = index.edgeToNodes.get(edgeId);
      if (!ends) return;
      const otherId = ends[0] === nodeId ? ends[1] : ends[0];
      if (seen.has(otherId)) return;
      const other = nodesById.get(otherId);
      if (!other) return;
      seen.add(otherId);
      out.push(other);
    });
    return out;
  }

  function sortNodes(nodes) {
    return nodes.slice().sort(function (a, b) {
      const rank = rankType(a.type) - rankType(b.type);
      if (rank) return rank;
      const left = String(a.label || "").toLowerCase();
      const right = String(b.label || "").toLowerCase();
      if (left < right) return -1;
      if (left > right) return 1;
      return 0;
    });
  }

  function connectionButton(node) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "conn";
    const mark = document.createElement("i");
    mark.setAttribute("data-group", node.group || "web");
    const label = document.createElement("span");
    label.className = "conn-label";
    label.textContent = prettyLabel(node);
    const kind = document.createElement("span");
    kind.className = "conn-type";
    kind.textContent = TYPE_NAME[node.type] || node.type;
    button.appendChild(mark);
    button.appendChild(label);
    button.appendChild(kind);
    button.addEventListener("click", function () {
      store.getState().select(node.id);
    });
    return button;
  }

  function connectionList(nodes) {
    const list = document.createElement("div");
    list.className = "conn-list";
    const ordered = sortNodes(nodes);
    ordered.slice(0, 40).forEach(function (node) {
      list.appendChild(connectionButton(node));
    });
    if (ordered.length > 40) {
      const more = document.createElement("p");
      more.className = "meta";
      more.textContent = (ordered.length - 40) + " more are in the connection list.";
      list.appendChild(more);
    }
    return list;
  }

  function metaLine(text) {
    const line = document.createElement("p");
    line.className = "meta";
    line.textContent = text;
    return line;
  }

  function countBits(nodes, selectedType) {
    const counts = { PERSON: 0, ORGANIZATION: 0, PHONE: 0, EMAIL: 0, ADDRESS: 0 };
    nodes.forEach(function (item) {
      if (counts[item.type] != null) counts[item.type] += 1;
    });
    const bits = [];
    function add(n, one, many) {
      if (n) bits.push(n + " " + (n === 1 ? one : many));
    }
    add(counts.PERSON, selectedType === "PERSON" ? "other person" : "person", selectedType === "PERSON" ? "other people" : "people");
    add(counts.ORGANIZATION, selectedType === "ORGANIZATION" ? "other organization" : "organization", selectedType === "ORGANIZATION" ? "other organizations" : "organizations");
    add(counts.PHONE, selectedType === "PHONE" ? "other phone" : "phone", selectedType === "PHONE" ? "other phones" : "phones");
    add(counts.EMAIL, selectedType === "EMAIL" ? "other email" : "email", selectedType === "EMAIL" ? "other emails" : "emails");
    add(counts.ADDRESS, selectedType === "ADDRESS" ? "other place" : "place", selectedType === "ADDRESS" ? "other places" : "places");
    return bits;
  }

  function joinBits(bits) {
    if (bits.length <= 1) return bits[0] || "";
    if (bits.length === 2) return bits[0] + " and " + bits[1];
    return bits.slice(0, -1).join(", ") + ", and " + bits[bits.length - 1];
  }

  function leadLine(text) {
    const line = document.createElement("p");
    line.className = "lead";
    line.textContent = text;
    return line;
  }

  function renderInspector(state) {
    detail.replaceChildren();
    const node = state.visibleNodes.find(function (item) { return item.id === state.selectedId; });
    if (!node) {
      detail.appendChild(metaLine("Select a person, phone, email, place, or source. This pane lists what it connects to."));
      statusEl.textContent = "Unreviewed";
      return;
    }
    const value = document.createElement("p");
    value.className = "value";
    value.textContent = node.label || node.value;
    detail.appendChild(value);
    const kind = document.createElement("p");
    kind.className = "kind";
    kind.textContent = TYPE_NAME[node.type] || node.type;
    detail.appendChild(kind);
    const direct = linkedNodes(node.id);
    if (node.type === "DOMAIN") {
      const findings = direct.filter(isFinding);
      const details = direct.filter(function (item) { return item.type === "PROVENANCE"; });
      const bits = countBits(findings, "");
      const lead = bits.length
        ? joinBits(bits) + " came from this source."
        : "No people, phones, emails, or places came from this source.";
      detail.appendChild(leadLine(lead));
      detail.appendChild(sectionTitle("Found here"));
      if (findings.length) detail.appendChild(connectionList(findings));
      else detail.appendChild(metaLine("No people, phones, emails, or places on this source."));
      if (details.length && !state.enabled.web) {
        detail.appendChild(metaLine(details.length + " page details stay in Web footprint."));
      } else if (details.length) {
        detail.appendChild(sectionTitle("Page details"));
        detail.appendChild(connectionList(details));
      }
      detail.appendChild(metaLine("Findings above were extracted from pages on this source."));
    } else {
      const sources = direct.filter(function (item) { return item.type === "DOMAIN"; });
      const seen = new Set([node.id]);
      const also = [];
      sources.forEach(function (source) {
        linkedNodes(source.id).forEach(function (item) {
          if (seen.has(item.id) || !isFinding(item)) return;
          seen.add(item.id);
          also.push(item);
        });
      });
      const names = sources.map(function (item) {
        return safeText(item.label || item.id).replace(/-/g, "\u2011");
      }).filter(Boolean);
      let where = "No source page is linked yet.";
      if (names.length === 1) where = "Found on " + names[0] + ".";
      else if (names.length === 2) where = "Found on " + names[0] + " and " + names[1] + ".";
      else if (names.length > 2) where = "Found on " + names[0] + ", " + names[1] + ", and " + (names.length - 2) + " more.";
      const pageWord = sources.length === 1 ? "that page." : "those pages.";
      const bits = countBits(also, node.type);
      const lead = bits.length
        ? where + " " + joinBits(bits) + (also.length === 1 ? " was" : " were") + " on " + pageWord
        : where + " Nothing else was extracted from " + pageWord;
      detail.appendChild(leadLine(lead));
      detail.appendChild(sectionTitle("Found on"));
      if (sources.length) detail.appendChild(connectionList(sources));
      else detail.appendChild(metaLine("No source page is linked to this yet."));
      detail.appendChild(sectionTitle("Also on this source"));
      if (also.length) detail.appendChild(connectionList(also));
      else detail.appendChild(metaLine("Nothing else was found on this source."));
      detail.appendChild(sectionTitle("Record"));
      if (node.value && node.value !== node.label) addLine(detail, "Value", node.value);
      addLine(detail, "Source", node.sourceDomain);
      addLine(detail, "Field", node.rawMetadataKey);
      addLine(detail, "Confidence", confidenceLabel(node.confidence));
      if ((node.observations || []).length > 1) {
        node.observations.forEach(function (item) {
          addLine(detail, "Also from", item.sourceDomain + " · " + item.rawMetadataKey + " · " + confidenceLabel(item.confidence));
        });
      }
    }
    statusEl.textContent = state.status[node.id] || "Unreviewed";
  }

  let lastSelected = "";
  store.subscribe(function (state) {
    renderFilters(state);
    renderHint(state);
    if (state.selectedId !== lastSelected) {
      lastSelected = state.selectedId;
      scrollSelection(state);
    }
    renderList(state);
    renderInspector(state);
    if (state.drawToken !== lastDraw) {
      lastDraw = state.drawToken;
      postDraw(state);
    }
  });

  search.addEventListener("input", function (event) {
    store.getState().setQuery(event.target.value);
  });
  document.querySelectorAll("button.filter").forEach(function (button) {
    button.addEventListener("click", function () {
      store.getState().toggleCategory(button.getAttribute("data-category"));
    });
  });
  document.getElementById("verify-entity").addEventListener("click", function () {
    const id = store.getState().selectedId;
    if (!id) return;
    store.getState().setStatus(id, "Verified");
  });
  document.getElementById("reject-entity").addEventListener("click", function () {
    const id = store.getState().selectedId;
    if (!id) return;
    store.getState().setStatus(id, "Rejected");
  });
  listHost.addEventListener("scroll", function () {
    renderList(store.getState());
  });
  if (typeof ResizeObserver === "function") {
    const listObserver = new ResizeObserver(function () {
      renderList(store.getState());
    });
    listObserver.observe(listHost);
  }

  function hitTest(event) {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const positions = store.getState().positions || {};
    let hit = "";
    let best = 18;
    store.getState().visibleNodes.forEach(function (node) {
      const pos = positions[node.id];
      if (!pos) return;
      const dx = pos.x - x;
      const dy = pos.y - y;
      const distance = Math.sqrt(dx * dx + dy * dy);
      const labelMax = pos.labelMax || 120;
      const band = Math.max(12, (pos.pitch || 24) / 2);
      const labelHit = x >= pos.x && x <= pos.x + labelMax + 16 && Math.abs(y - pos.y) <= band;
      const score = labelHit ? 0 : distance;
      if ((labelHit || distance <= best) && score <= best) {
        best = score;
        hit = node.id;
      }
    });
    return hit;
  }

  canvas.addEventListener("click", function (event) {
    store.getState().select(hitTest(event));
  });
  canvas.addEventListener("mousemove", function (event) {
    canvas.style.cursor = hitTest(event) ? "pointer" : "default";
  });

  function applySize(size) {
    if (!ready) {
      canvas.width = size.width;
      canvas.height = size.height;
    }
    canvas.style.width = size.width + "px";
    canvas.style.height = size.height + "px";
    host.dataset.canvasWidth = String(size.width);
    host.dataset.canvasHeight = String(size.height);
  }

  function boot(attempt) {
    const size = measure();
    if ((size.width < 40 || size.height < 40) && attempt < 40) {
      requestAnimationFrame(function () { boot(attempt + 1); });
      return;
    }
    applySize(size);
    const state = store.getState();
    const message = pending || drawMessage(state, size);
    message.width = size.width;
    message.height = size.height;
    try {
      const offscreen = canvas.transferControlToOffscreen();
      window.__OFFSCREEN__ = true;
      message.canvas = offscreen;
      worker.postMessage(message, [offscreen]);
      ready = true;
      window.__WORKER_USED__ = true;
    } catch (error) {
      window.__OFFSCREEN__ = false;
      window.__OFFSCREEN_ERROR__ = String(error && error.message ? error.message : error);
    }
    renderList(store.getState());
  }

  const canWorker = typeof Worker === "function";
  const canOffscreen = typeof OffscreenCanvas === "function" &&
    typeof HTMLCanvasElement !== "undefined" &&
    typeof HTMLCanvasElement.prototype.transferControlToOffscreen === "function";
  if (canWorker && canOffscreen) {
    const blob = new Blob([WORKER_SOURCE], { type: "text/javascript" });
    worker = new Worker(URL.createObjectURL(blob));
    worker.onmessage = function (event) {
      const data = event.data || {};
      if (data.type !== "painted") return;
      window.__WORKER_PAINTED__ = true;
      window.__CANVAS_SIZE__ = { width: data.width, height: data.height };
      window.__GRAPH_POSITIONS__ = data.positions;
      if (data.height && data.height > host.clientHeight + 4) {
        host.style.minHeight = data.height + "px";
        canvas.style.height = data.height + "px";
      }
      store.getState().setPositions(data.positions || {});
    };
    worker.onerror = function (error) {
      window.__WORKER_ERROR__ = String(error.message || error);
      if (error.preventDefault) error.preventDefault();
    };
    store.getState().setQuery("");
    boot(0);
    window.addEventListener("resize", function () {
      if (!ready) return;
      const size = measure();
      renderList(store.getState());
      if (size.width === lastSize.width && size.height === lastSize.height) return;
      applySize(size);
      postDraw(store.getState());
    });
  } else {
    window.__WORKER_USED__ = false;
    window.__OFFSCREEN__ = false;
    store.getState().setQuery("");
  }
})();
