# Report UI and local inference wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the HTML OSINT relationship report into a readable, filterable network view, and add a setup wizard that runs summarization through a local or open model the user picks.

**Architecture:** Keep crawl and SQLite behavior. Extract a pure graph builder and an HTML renderer from `ScraperApp.export_report` in `src/main.py`. Put inference behind a domain protocol. Tk only collects a `ModelConfig` and calls application use cases. Optional heavy libraries load inside infrastructure adapters.

**Tech Stack:** Python 3, existing ttkbootstrap / Flask / httpx / BeautifulSoup app, pytest, stdlib HTML rendering, optional `huggingface_hub`, `llama-cpp-python`, `mlx-lm`, `onnxruntime`.

## Global Constraints

- Do not add stealth crawling, captcha bypass, credential collection, authentication bypass, or new search-dork types.
- Do not edit `start.sh`. Leave the existing API key default in place.
- Do not download a model until the wizard user confirms the repo id or file path.
- Domain modules use the standard library only.
- New UI widgets that tests can see expose `data-testid` in the HTML report. Tk widgets that tests target use an explicit attribute name stored on the widget (`testid`).
- Optional inference imports must fail soft with `InferenceResult.ok == False` and a one-line install hint.
- Do not require a network in unit tests. Fake the backend and do not call Hugging Face, Ollama, or Gemini.

---

### Task 1: Graph model from scrape rows

**Files:**
- Create: `src/domain/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: dict rows shaped like `_prepare_export_data()` (`SourceURL`, `Entities` JSON string or dict, `Title` optional).
- Produces: `GraphNode(id: str, label: str, group: str)`, `GraphEdge(source: str, target: str, relation: str)`, `RelationGraph(nodes: list, edges: list)`, `build_relation_graph(rows: list) -> RelationGraph`.

- [ ] **Step 1: Write the failing test**

```python
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
    assert graph.edges[0].source == "https://example.com/a"
    assert graph.edges[0].target == "email:ada@example.com"
    assert graph.edges[0].relation == "email"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_graph.py::test_build_relation_graph_links_page_to_email -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `src.domain.graph`

- [ ] **Step 3: Write minimal implementation**

```python
import json
from dataclasses import dataclass

@dataclass(frozen=True)
class GraphNode:
    id: str
    label: str
    group: str

@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str

@dataclass(frozen=True)
class RelationGraph:
    nodes: list
    edges: list

def build_relation_graph(rows):
    nodes = {}
    edges = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        source = row.get("SourceURL") or ""
        if not source:
            continue
        if source not in nodes:
            label = source
            try:
                from urllib.parse import urlparse
                host = urlparse(source).hostname
                if host:
                    label = host
            except Exception:
                pass
            nodes[source] = GraphNode(source, label, "domain")
        entities = row.get("Entities") or {}
        if isinstance(entities, str):
            try:
                entities = json.loads(entities)
            except json.JSONDecodeError:
                entities = {}
        if not isinstance(entities, dict):
            continue
        for relation, values in entities.items():
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list):
                continue
            for value in values:
                if not value:
                    continue
                node_id = f"{relation}:{value}"
                if node_id not in nodes:
                    nodes[node_id] = GraphNode(node_id, str(value), str(relation))
                edges.append(GraphEdge(source, node_id, str(relation)))
    return RelationGraph(list(nodes.values()), edges)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_graph.py::test_build_relation_graph_links_page_to_email -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_graph.py src/domain/graph.py docs/adr/ADR-001-pytest-and-layers.md
git commit -m "feat: build a relation graph from scrape rows"
```

### Task 2: Self-contained HTML report

**Files:**
- Create: `src/infrastructure/report_html.py`
- Modify: `src/main.py` `export_report` (around lines 1121-1173) to call `render_report_html`
- Test: `tests/test_report_html.py`

**Interfaces:**
- Consumes: `RelationGraph` from `src.domain.graph.build_relation_graph`
- Produces: `render_report_html(graph: RelationGraph, title: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
from src.domain.graph import GraphNode, GraphEdge, RelationGraph
from src.infrastructure.report_html import render_report_html

def test_report_has_filters_search_and_testid():
    graph = RelationGraph(
        nodes=[
            GraphNode("https://example.com", "example.com", "domain"),
            GraphNode("email:ada@example.com", "ada@example.com", "email"),
        ],
        edges=[GraphEdge("https://example.com", "email:ada@example.com", "email")],
    )
    html = render_report_html(graph, title="OSINT Relationship Map")
    assert 'data-testid="report-title"' in html
    assert 'data-testid="graph-search"' in html
    assert 'data-testid="group-filter-email"' in html
    assert 'data-testid="network"' in html
    assert "ada@example.com" in html
    assert "unpkg.com" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_report_html.py::test_report_has_filters_search_and_testid -v`
Expected: FAIL with import error for `render_report_html`

- [ ] **Step 3: Write minimal implementation**

Render one HTML document. Embed graph JSON via `json.dumps`. Include a search input, one button per node group, a node-detail aside, and a legend. Draw edges as an SVG or as a list plus a small canvas script that does not load a CDN. Escape text with `html.escape`. Put `data-testid` on the title, search box, network pane, and each group filter.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_report_html.py::test_report_has_filters_search_and_testid -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_report_html.py src/infrastructure/report_html.py src/main.py
git commit -m "feat: render a filterable offline HTML relationship report"
```

### Task 3: Inference port and wizard config

**Files:**
- Create: `src/domain/inference.py`
- Create: `src/application/wizard.py`
- Test: `tests/test_inference_config.py`

**Interfaces:**
- Produces: `ModelConfig(backend: str, model_id: str, model_path: str, endpoint: str)`, `InferenceResult(ok: bool, text: str, error: str)`, `validate_model_config(config: ModelConfig) -> InferenceResult`, `BACKENDS = ("huggingface", "llama_cpp", "mlx", "onnx", "gguf_file", "weights_dir", "ollama", "llamacpp_server")`.

- [ ] **Step 1: Write the failing test**

```python
from src.domain.inference import ModelConfig, validate_model_config

def test_gguf_backend_requires_existing_choice_not_a_download():
    missing = validate_model_config(ModelConfig("gguf_file", "", "", ""))
    assert missing.ok is False
    assert "path" in missing.error.lower()

def test_huggingface_id_is_accepted_without_downloading():
    result = validate_model_config(ModelConfig("huggingface", "org/model", "", ""))
    assert result.ok is True

def test_llama_cpp_is_valid_only_when_model_path_is_set():
    ok = validate_model_config(ModelConfig("llama_cpp", "", "/models/foo.gguf", ""))
    assert ok.ok is True
    assert ok.error == ""
    missing = validate_model_config(ModelConfig("llama_cpp", "org/model", "", "http://127.0.0.1:8080"))
    assert missing.ok is False
    assert "path" in missing.error.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_inference_config.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write minimal implementation**

`validate_model_config` checks the backend is in `BACKENDS` and performs no file, socket, or HTTP I/O. `gguf_file`, `onnx`, and `llama_cpp` require a non-empty `model_path`; for those three, `model_id` and `endpoint` do not make the config valid. `huggingface` requires a `model_id` containing `/`. `ollama` and `llamacpp_server` require an endpoint that starts with `http://` or `https://`. `mlx` and `weights_dir` require a non-empty `model_path` or a non-empty `model_id`. A valid result has `ok is True` and `error == ""`. An invalid result has `ok is False` and a non-empty `error`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_inference_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/inference.py src/application/wizard.py tests/test_inference_config.py docs/adr/ADR-002-local-inference-ports.md
git commit -m "feat: validate local inference wizard choices without downloading"
```

### Task 4: Adapters and wizard screen

**Files:**
- Create: `src/infrastructure/inference_factory.py`
- Create: `src/presentation/model_wizard.py`
- Modify: `src/main.py` to add a Models button that opens the wizard
- Modify: `requirements.txt` to add `pytest`
- Do not modify: `start.sh`
- Test: `tests/test_inference_factory.py`

**Interfaces:**
- Consumes: `ModelConfig`, `InferenceResult`
- Produces: `build_backend(config: ModelConfig)` returning an object with `complete(prompt: str) -> InferenceResult`. `FakeBackend` is used in tests. Real adapters catch `ImportError`.

- [ ] **Step 1: Write the failing test**

```python
from src.domain.inference import ModelConfig
from src.infrastructure.inference_factory import build_backend

def test_unknown_package_is_a_soft_error(monkeypatch):
    config = ModelConfig("huggingface", "org/model", "", "")
    backend = build_backend(config)
    result = backend.complete("Summarize this graph in one sentence.")
    assert result.ok is False
    assert result.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_inference_factory.py::test_unknown_package_is_a_soft_error -v`
Expected: FAIL with import error

- [ ] **Step 3: Write minimal implementation**

Factory returns a backend whose `complete` tries the optional import for that backend and, on failure, returns `InferenceResult(False, "", "Install <package> to use <backend>.")`. The Tk wizard is a `ttk.Toplevel` with a backend combobox, a model id entry, a file picker, an endpoint entry, a test button, and `testid` values `wizard-backend`, `wizard-model-id`, `wizard-path`, `wizard-endpoint`, `wizard-test`. Wire `export_report` in `src/main.py` to `render_report_html(build_relation_graph(data), ...)`. Do not change `start.sh`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_graph.py tests/test_report_html.py tests/test_inference_config.py tests/test_inference_factory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/inference_factory.py src/presentation/model_wizard.py src/main.py requirements.txt tests/test_inference_factory.py
git commit -m "feat: add a local-model setup wizard and wire it to the report"
```

## Requirements oracles the next gate must copy

These sentences are the testable form of the four checks that failed the last requirements gate. Copy them into FR acceptance criteria. Do not weaken them.

- FR-003 llama.cpp success: `validate_model_config(ModelConfig("llama_cpp", "", "/models/foo.gguf", ""))` returns `ok is True` and `error == ""`. `validate_model_config(ModelConfig("llama_cpp", "org/model", "", "http://127.0.0.1:8080"))` returns `ok is False` and the error contains `path`. Neither call reads the filesystem or opens a socket. `model_id` and `endpoint` do not make `llama_cpp` valid.
- FR-002 open behavior: after `ScraperGUI.export_report` writes the HTML file, it calls `webbrowser.open` once with `pathlib.Path(path).resolve().as_uri()`. An empty `_all_results_cache` calls `messagebox.showinfo("No Data", "Run a crawl before exporting results.")` and does not call `webbrowser.open` and does not write a file.
- FR-004 soft failures, exact one-line errors, no exception: missing `huggingface_hub` on backend `huggingface` returns `Install huggingface_hub to use huggingface.`; missing `llama-cpp-python` on `llama_cpp` returns `Install llama-cpp-python to use llama_cpp.`; missing `mlx-lm` on `mlx` returns `Install mlx-lm to use mlx.`; missing `onnxruntime` on `onnx` returns `Install onnxruntime to use onnx.`; missing `llama-cpp-python` on `gguf_file` returns `Install llama-cpp-python to use gguf_file.`; missing `huggingface_hub` on `weights_dir` returns `Install huggingface_hub to use weights_dir.`. Each result has `ok is False`, `text == ""`, and `error` equal to that single line.
- NFR-002 unchanged surfaces: `set(osint_helper.DORKS) == {"files", "configs", "social", "login", "directory", "email_lists"}`. `apply_dork("acme", "files") == "acme (ext:pdf OR ext:docx OR ext:xlsx OR ext:pptx OR ext:txt)"`. `apply_dork("acme", "not-a-dork") == "acme"`. `DatabaseManager.save_result` stores `json.dumps(item["Entities"])` in the `entities` column when `Entities` is present, and `get_results_for_session` returns that value under the key `Entities` as a dict. `start.sh` SHA-256 stays `31b6cd1a6a952aecce53c3b5292e61fed20618f1f46fc09fcb808968c24b431a`. The test asserts the hash only. It does not print file contents.

## Second-gate oracles

Copy these as acceptance criteria. Do not add a criterion that is not one Given/When/Then with one observable. Do not change `src/database_manager.py` or `start.sh`.

- FR-001 invalid entities, separate from the valid JSON case: Given `SourceURL` `https://example.com/a` and `Entities` the string `not-json`, When `build_relation_graph` runs, Then it does not raise, the page node id `https://example.com/a` exists, and there are zero edges.
- NFR-001 imports: From the repository root, `python3 -c "import src.domain.graph"` exits 0 after `src/__init__.py` and `src/domain/__init__.py` exist. `python3 -c "import sys; sys.path.insert(0, 'src'); import osint_helper; import database_manager"` exits 0. Tests do not import `src.main` or `src.server`. No criterion may say "neither import style breaks the other" or "start.sh is not the thing that changes."
- NFR-002 storage matches `DatabaseManager.save_result` as written: when `item.get("Entities")` is truthy, the `entities` column is `json.dumps` of that value; when `Entities` is missing, `None`, `{}`, or `""`, the column is `""`. The round-trip fixture is only `{"email": ["ada@example.com"]}`: `get_results_for_session` returns `Entities` equal to that dict. A falsy `Entities` is not dumped.
- `describe()` returns a `str` equal to `ModelConfig.backend`. `health_check()` and `complete(prompt)` return `InferenceResult`. A missing optional package makes both `health_check` and `complete` return `ok False`, `text ""`, and the same one-line install error, and neither raises.
- The HTML report never calls `complete()`. The control with testid `wizard-test` calls `complete("Summarize this graph in one sentence.")` and writes `InferenceResult.text` when `ok` is True, otherwise `InferenceResult.error`, into the widget with testid `wizard-result`.
- `ollama` and `llamacpp_server` have no install package. A failed HTTP call returns `ok False`, `text ""`, and `error` exactly `Endpoint unreachable.`

## Self-review

- Spec coverage: filterable report (Task 2), relation graph (Task 1), Hugging Face / llama / MLX / GGUF / ONNX / weights / Ollama / llama.cpp server (Tasks 3-4), wizard (Task 4). `start.sh` is out of scope.
- No new offensive collection features.
- Type names match across tasks: `RelationGraph`, `ModelConfig`, `InferenceResult`, `build_relation_graph`, `render_report_html`, `build_backend`.
