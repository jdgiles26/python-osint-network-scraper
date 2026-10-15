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


def _clamp_tokens(max_tokens: int) -> int:
    try:
        value = int(max_tokens)
    except (TypeError, ValueError):
        value = 80
    return min(512, max(16, value))


def _module_available(module_name: str) -> bool:
    try:
        _try_import(module_name)
    except ImportError:
        return False
    return True


def _hf_generate(model_id: str, prompt: str, max_tokens: int) -> str:
    """Answer with a confirmed Hugging Face model.

    A local transformers install downloads the snapshot and generates from it.
    Otherwise the Hub inference client is used. Nothing here runs before Confirm.
    """
    if _module_available("transformers"):
        from huggingface_hub import snapshot_download

        local_dir = snapshot_download(model_id)
        text = _hf_local_text(local_dir, prompt, max_tokens)
        if text:
            return text
    text = _hf_hosted_text(model_id, prompt, max_tokens)
    if text:
        return text
    raise RuntimeError("Install transformers to generate with the downloaded Hugging Face model.")


def _hf_local_text(local_dir: str, prompt: str, max_tokens: int) -> str:
    from transformers import pipeline

    pipe = pipeline("text-generation", model=local_dir)
    output = pipe(prompt, max_new_tokens=max_tokens, return_full_text=False)
    if isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, dict):
            return (first.get("generated_text") or "").strip()
    return ""


def _hf_hosted_text(model_id: str, prompt: str, max_tokens: int) -> str:
    try:
        from huggingface_hub import InferenceClient
    except ImportError:
        return ""
    try:
        client = InferenceClient(model=model_id, timeout=30)
    except TypeError:
        client = InferenceClient(model=model_id)
    try:
        result = client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        text = result.choices[0].message.content
        if text and str(text).strip():
            return str(text).strip()
    except Exception:
        pass
    try:
        text = client.text_generation(prompt, max_new_tokens=max_tokens)
    except Exception:
        return ""
    return (text or "").strip()


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

    def complete(self, prompt: str, max_tokens: int = 80) -> InferenceResult:
        missing = self._missing()
        if missing is not None:
            return missing
        if self.config.backend in CONFIRM_FIRST and not self.config.confirmed:
            return InferenceResult(False, "", "Confirm the model before download.")
        checked = validate_model_config(self.config)
        if not checked.ok:
            return checked
        limit = _clamp_tokens(max_tokens)
        try:
            return self._run(prompt, limit)
        except Exception as exc:
            if self.config.backend in {"ollama", "llamacpp_server"}:
                return _unreachable()
            message = str(exc).strip() or "The model did not answer."
            return InferenceResult(False, "", message)

    def _run(self, prompt: str, max_tokens: int) -> InferenceResult:
        backend = self.config.backend
        if backend in {"ollama", "llamacpp_server"}:
            return self._run_http(prompt, max_tokens)
        if backend == "huggingface":
            text = (_hf_generate(self.config.model_id, prompt, max_tokens) or "").strip()
            if not text:
                return InferenceResult(False, "", "The model did not answer.")
            return InferenceResult(True, text, "")
        if backend == "weights_dir":
            return InferenceResult(True, f"Weights directory {self.config.model_path or self.config.model_id} is ready.", "")
        if backend in {"llama_cpp", "gguf_file"}:
            from llama_cpp import Llama
            model = Llama(model_path=self.config.model_path, n_ctx=2048, verbose=False)
            reply = model.create_completion(prompt, max_tokens=max_tokens)
            text = reply["choices"][0]["text"]
            return InferenceResult(True, text.strip(), "")
        if backend == "mlx":
            from mlx_lm import generate, load
            target = self.config.model_path or self.config.model_id
            model, tokenizer = load(target)
            return InferenceResult(True, generate(model, tokenizer, prompt=prompt, max_tokens=max_tokens), "")
        if backend == "onnx":
            import onnxruntime
            session = onnxruntime.InferenceSession(self.config.model_path)
            return InferenceResult(True, f"Loaded ONNX session with {len(session.get_inputs())} inputs.", "")
        return InferenceResult(False, "", f"Unknown backend: {backend}")

    def _run_http(self, prompt: str, max_tokens: int) -> InferenceResult:
        base = self.config.endpoint.rstrip("/")
        if self.config.backend == "ollama":
            url = base if base.endswith("/api/generate") else base + "/api/generate"
            payload = {
                "model": self.config.model_id or "llama3.2",
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens},
            }
            data = _post_json(url, payload)
            text = data.get("response") or ""
        else:
            url = base if base.endswith("/completion") else base + "/completion"
            data = _post_json(url, {"prompt": prompt, "n_predict": max_tokens})
            text = data.get("content") or ""
        if not text:
            return _unreachable()
        return InferenceResult(True, text, "")


def build_backend(config: ModelConfig) -> InferenceBackend:
    return InferenceBackend(config)
