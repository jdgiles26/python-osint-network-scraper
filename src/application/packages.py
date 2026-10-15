"""Pip packages each model backend needs. Ollama and a llama.cpp server are apps."""

PACKAGES = {
    "huggingface": ("huggingface_hub", "transformers"),
    "weights_dir": ("huggingface_hub", "transformers"),
    "llama_cpp": ("llama-cpp-python",),
    "gguf_file": ("llama-cpp-python",),
    "mlx": ("mlx-lm",),
    "onnx": ("onnxruntime",),
    "ollama": (),
    "llamacpp_server": (),
}

NO_LIBRARY = "Ollama and a llama.cpp server are separate apps. There is no Python library to install."


def packages_for(backend: str) -> tuple:
    return PACKAGES.get((backend or "").strip(), ())


def install_button_label(backend: str) -> str:
    packages = packages_for(backend)
    if not packages:
        return "No library to install"
    return "Install " + " + ".join(packages)
