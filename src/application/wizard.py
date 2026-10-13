PROMPT = "Summarize this graph in one sentence."

BACKEND_HELP = {
    "huggingface": "Download a model from Hugging Face after you confirm. Use an id such as org/model-name.",
    "llama_cpp": "Run a .gguf file on this Mac with llama.cpp. Pick the file in the next step.",
    "mlx": "Run a model with Apple MLX. Pick a folder or type a model id.",
    "onnx": "Load an .onnx file you already have. Nothing is downloaded.",
    "gguf_file": "Use a .gguf file you already have. Nothing is downloaded.",
    "weights_dir": "Use a folder of model weights. A download happens only after you confirm.",
    "ollama": "Talk to Ollama on this Mac. The usual address is http://127.0.0.1:11434.",
    "llamacpp_server": "Talk to a llama.cpp server. The usual address is http://127.0.0.1:8080.",
}


def fields_for(backend: str) -> tuple:
    if backend == "huggingface":
        return ("model_id",)
    if backend in {"ollama", "llamacpp_server"}:
        return ("model_id", "endpoint")
    if backend in {"mlx", "weights_dir"}:
        return ("model_id", "path")
    if backend in {"llama_cpp", "gguf_file", "onnx"}:
        return ("path",)
    return ("model_id", "path", "endpoint")


def default_endpoint(backend: str) -> str:
    if backend == "ollama":
        return "http://127.0.0.1:11434"
    if backend == "llamacpp_server":
        return "http://127.0.0.1:8080"
    return ""


def run_wizard_test(backend) -> str:
    result = backend.complete(PROMPT)
    if result.ok:
        return result.text
    return result.error
