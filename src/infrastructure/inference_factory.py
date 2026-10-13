import json
from typing import Optional
from urllib import request

from src.domain.inference import InferenceResult, ModelConfig, validate_model_config


INSTALL = {
    "huggingface": ("huggingface_hub", "Install huggingface_hub to use huggingface."),
    "llama_cpp": ("llama_cpp", "Install llama-cpp-python to use llama_cpp."),
    "mlx": ("mlx_lm", "Install mlx-lm to use mlx."),
    "onnx": ("onnxruntime", "Install onnxruntime to use onnx."),
    "gguf_file": ("llama_cpp", "Install llama-cpp-python to use gguf_file."),
    "weights_dir": ("huggingface_hub", "Install huggingface_hub to use weights_dir."),
}
CONFIRM_FIRST = {"huggingface", "weights_dir"}


def _try_import(module_name: str):
    __import__(module_name)


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _unreachable() -> InferenceResult:
    return InferenceResult(False, "", "Endpoint unreachable.")


class InferenceBackend:
    def __init__(self, config: ModelConfig):
        self.config = config

    def describe(self) -> str:
        return self.config.backend

    def _missing(self) -> Optional[InferenceResult]:
        package = INSTALL.get(self.config.backend)
        if package is None:
            return None
        module_name, message = package
        try:
            _try_import(module_name)
        except ImportError:
            return InferenceResult(False, "", message)
        return None

    def health_check(self) -> InferenceResult:
        missing = self._missing()
        if missing is not None:
            return missing
        checked = validate_model_config(self.config)
        if not checked.ok:
            return checked
        return InferenceResult(True, "ready", "")

    def complete(self, prompt: str) -> InferenceResult:
        missing = self._missing()
        if missing is not None:
            return missing
        if self.config.backend in CONFIRM_FIRST and not self.config.confirmed:
            return InferenceResult(False, "", "Confirm the model before download.")
        checked = validate_model_config(self.config)
        if not checked.ok:
            return checked
        try:
            return self._run(prompt)
        except Exception:
            if self.config.backend in {"ollama", "llamacpp_server"}:
                return _unreachable()
            return InferenceResult(False, "", "The model did not answer.")

    def _run(self, prompt: str) -> InferenceResult:
        backend = self.config.backend
        if backend in {"ollama", "llamacpp_server"}:
            return self._run_http(prompt)
        if backend == "huggingface":
            from huggingface_hub import snapshot_download
            path = snapshot_download(self.config.model_id)
            return InferenceResult(True, f"Downloaded {self.config.model_id} to {path}", "")
        if backend == "weights_dir":
            return InferenceResult(True, f"Weights directory {self.config.model_path or self.config.model_id} is ready.", "")
        if backend in {"llama_cpp", "gguf_file"}:
            from llama_cpp import Llama
            model = Llama(model_path=self.config.model_path, n_ctx=512, verbose=False)
            reply = model.create_completion(prompt, max_tokens=80)
            text = reply["choices"][0]["text"]
            return InferenceResult(True, text.strip(), "")
        if backend == "mlx":
            from mlx_lm import generate, load
            target = self.config.model_path or self.config.model_id
            model, tokenizer = load(target)
            return InferenceResult(True, generate(model, tokenizer, prompt=prompt, max_tokens=80), "")
        if backend == "onnx":
            import onnxruntime
            session = onnxruntime.InferenceSession(self.config.model_path)
            return InferenceResult(True, f"Loaded ONNX session with {len(session.get_inputs())} inputs.", "")
        return InferenceResult(False, "", f"Unknown backend: {backend}")

    def _run_http(self, prompt: str) -> InferenceResult:
        base = self.config.endpoint.rstrip("/")
        if self.config.backend == "ollama":
            url = base if base.endswith("/api/generate") else base + "/api/generate"
            payload = {"model": self.config.model_id or "llama3.2", "prompt": prompt, "stream": False}
            data = _post_json(url, payload)
            text = data.get("response") or ""
        else:
            url = base if base.endswith("/completion") else base + "/completion"
            data = _post_json(url, {"prompt": prompt, "n_predict": 80})
            text = data.get("content") or ""
        if not text:
            return _unreachable()
        return InferenceResult(True, text, "")


def build_backend(config: ModelConfig) -> InferenceBackend:
    return InferenceBackend(config)
