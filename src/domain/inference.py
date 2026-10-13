from dataclasses import dataclass


BACKENDS = (
    "huggingface",
    "llama_cpp",
    "mlx",
    "onnx",
    "gguf_file",
    "weights_dir",
    "ollama",
    "llamacpp_server",
)

PATH_BACKENDS = ("gguf_file", "onnx", "llama_cpp")
EITHER_BACKENDS = ("mlx", "weights_dir")
HTTP_BACKENDS = ("ollama", "llamacpp_server")


@dataclass(frozen=True)
class ModelConfig:
    backend: str
    model_id: str = ""
    model_path: str = ""
    endpoint: str = ""
    confirmed: bool = False


@dataclass(frozen=True)
class InferenceResult:
    ok: bool
    text: str
    error: str


def _fail(message: str) -> InferenceResult:
    return InferenceResult(False, "", message)


def _ok() -> InferenceResult:
    return InferenceResult(True, "", "")


def validate_model_config(config: ModelConfig) -> InferenceResult:
    backend = (config.backend or "").strip()
    if backend not in BACKENDS:
        return _fail(f"Unknown backend: {backend or 'empty'}")
    model_id = (config.model_id or "").strip()
    model_path = (config.model_path or "").strip()
    endpoint = (config.endpoint or "").strip()
    if backend in PATH_BACKENDS:
        if not model_path:
            return _fail("A model path is required.")
        return _ok()
    if backend == "huggingface":
        if "/" not in model_id:
            return _fail("A Hugging Face model id like org/model is required.")
        return _ok()
    if backend in HTTP_BACKENDS:
        if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
            return _fail("An http:// or https:// endpoint is required.")
        return _ok()
    if backend in EITHER_BACKENDS:
        if not model_path and not model_id:
            return _fail("A model path or a model id is required.")
        return _ok()
    return _fail(f"Unknown backend: {backend}")
