"""Deterministic canvas layout.

The report worker runs the same placement in JavaScript. Pytest calls this
function directly. Positions stay inside the pane and spread across it.
"""
import math


def layout_graph(nodes, edges, width, height):
    width = max(int(width or 0), 1)
    height = max(int(height or 0), 1)
    grouped = {}
    order = ("people", "contact", "locations", "web")
    for node in nodes or []:
        group = getattr(node, "group", None)
        if group is None and isinstance(node, dict):
            group = node.get("group") or "web"
        group = group or "web"
        if group not in order:
            group = "web"
        node_id = getattr(node, "id", None)
        if node_id is None and isinstance(node, dict):
            node_id = node.get("id")
        if not node_id:
            continue
        grouped.setdefault(group, []).append(node_id)
    present = [(group, grouped[group]) for group in order if grouped.get(group)]
    if not present:
        return {}
    columns = 2 if len(present) > 1 else 1
    rows = max(1, math.ceil(len(present) / columns))
    positions = {}
    pad = 0.08
    for index, (_group, members) in enumerate(present):
        column = index % columns
        row = index // columns
        cell_w = width / columns
        cell_h = height / rows
        left = cell_w * column + cell_w * pad
        top = cell_h * row + cell_h * pad
        inner_w = cell_w * (1 - 2 * pad)
        inner_h = cell_h * (1 - 2 * pad)
        grid_cols = max(1, math.ceil(math.sqrt(len(members))))
        grid_rows = max(1, math.ceil(len(members) / grid_cols))
        for offset, node_id in enumerate(members):
            grid_row = offset // grid_cols
            grid_col = offset % grid_cols
            x = left + inner_w * ((grid_col + 0.5) / grid_cols)
            y = top + inner_h * ((grid_row + 0.5) / grid_rows)
            positions[node_id] = (x, y)
    return positions
