# ADR-002: Local and open inference behind one port

## Status: Accepted

## Context

The app can generate CSS selectors only through Google Gemini (`src/ai_helper.py`). The requested capability is on-the-fly local inference: Hugging Face downloads, llama.cpp, MLX, user-supplied `.gguf` / `.onnx` / weight directories, and a user-run open local server (Ollama or a llama.cpp server). Paid cloud keys stay optional and are never required.

## Decision

- Domain defines `InferenceBackend` with `describe()`, `health_check()`, and `complete(prompt) -> InferenceResult`.
- Infrastructure adapters implement that protocol. The wizard never imports `transformers`, `mlx`, `llama_cpp`, or `onnxruntime` directly.
- Missing optional packages return a structured error telling the user the exact install command. They do not crash the app.
- Model files are read only from a path the user picked, or from a Hugging Face repo id the user typed. Nothing is downloaded until the user confirms in the wizard.
- Report narrative uses the same port. Scraping and search behavior are unchanged.

## Consequences (Positive / Negative / Neutral)

- Positive: one wizard covers every backend. Tests can use a fake backend.
- Negative: each adapter is best-effort. A machine may lack MLX (non-Apple) or a GPU.
- Neutral: Gemini remains available as a legacy adapter, configured only from the environment or the settings field.

## Supports: FR-003 FR-004 FR-005

## Validation: Security | Testability
