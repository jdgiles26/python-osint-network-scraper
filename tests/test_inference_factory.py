from urllib.error import URLError

import src.infrastructure.inference_factory as factory
from src.application.wizard import PROMPT, run_wizard_test
from src.domain.inference import ModelConfig


def _blocked_import(_module_name):
    raise ImportError(_module_name)


def test_unknown_package_is_a_soft_error():
    config = ModelConfig("huggingface", "org/model", "", "", confirmed=True)
    backend = factory.build_backend(config)
    backend._missing = lambda: factory.InferenceResult(False, "", "Install huggingface_hub to use huggingface.")
    result = backend.complete(PROMPT)
    assert result.ok is False
    assert result.error


def test_missing_packages_use_the_exact_install_line(monkeypatch):
    monkeypatch.setattr(factory, "_try_import", _blocked_import)
    expected = {
        "huggingface": "Install huggingface_hub to use huggingface.",
        "llama_cpp": "Install llama-cpp-python to use llama_cpp.",
        "mlx": "Install mlx-lm to use mlx.",
        "onnx": "Install onnxruntime to use onnx.",
        "gguf_file": "Install llama-cpp-python to use gguf_file.",
        "weights_dir": "Install huggingface_hub to use weights_dir.",
    }
    for backend_name, message in expected.items():
        config = ModelConfig(backend_name, "org/model", "/tmp/model.gguf", "http://127.0.0.1:9", confirmed=True)
        backend = factory.build_backend(config)
        for result in (backend.complete(PROMPT), backend.health_check()):
            assert result.ok is False
            assert result.text == ""
            assert result.error == message
        assert backend.describe() == backend_name


def test_huggingface_does_not_download_before_confirm(monkeypatch):
    monkeypatch.setattr(factory, "_try_import", lambda _name: None)
    config = ModelConfig("huggingface", "org/model", "", "")
    result = factory.build_backend(config).complete(PROMPT)
    assert result.ok is False
    assert result.error == "Confirm the model before download."


def test_ollama_http_failure_is_endpoint_unreachable(monkeypatch):
    def _down(_url, _payload):
        raise URLError("refused")

    monkeypatch.setattr(factory, "_post_json", _down)
    config = ModelConfig("ollama", "llama3.2", "", "http://127.0.0.1:9")
    result = factory.build_backend(config).complete(PROMPT)
    assert result.ok is False
    assert result.text == ""
    assert result.error == "Endpoint unreachable."


def test_wizard_shows_only_the_fields_a_backend_needs():
    from src.application.wizard import default_endpoint, fields_for

    assert fields_for("huggingface") == ("model_id",)
    assert fields_for("gguf_file") == ("path",)
    assert fields_for("ollama") == ("model_id", "endpoint")
    assert default_endpoint("ollama") == "http://127.0.0.1:11434"
    assert default_endpoint("llamacpp_server") == "http://127.0.0.1:8080"
    assert default_endpoint("onnx") == ""


def test_confirmed_huggingface_returns_generated_text(monkeypatch):
    monkeypatch.setattr(factory, "_try_import", lambda _name: None)

    def _answer(model_id, prompt, max_tokens):
        return f"{model_id}:{max_tokens}:{prompt}"

    monkeypatch.setattr(factory, "_hf_generate", _answer)
    config = ModelConfig("huggingface", "org/model", "", "", confirmed=True)
    result = factory.build_backend(config).complete("Who is Ada?", max_tokens=120)
    assert result.ok is True
    assert result.text == "org/model:120:Who is Ada?"
    assert "Downloaded" not in result.text


def test_huggingface_generation_error_is_kept(monkeypatch):
    monkeypatch.setattr(factory, "_try_import", lambda _name: None)

    def _boom(_model_id, _prompt, _max_tokens):
        raise RuntimeError("Install transformers to generate with the downloaded Hugging Face model.")

    monkeypatch.setattr(factory, "_hf_generate", _boom)
    config = ModelConfig("huggingface", "org/model", "", "", confirmed=True)
    result = factory.build_backend(config).complete("hello")
    assert result.ok is False
    assert result.text == ""
    assert result.error == "Install transformers to generate with the downloaded Hugging Face model."


def test_wizard_test_writes_text_or_error():
    class Fake:
        def complete(self, prompt):
            assert prompt == PROMPT
            return factory.InferenceResult(True, "Ada maintains example.com.", "")

    assert run_wizard_test(Fake()) == "Ada maintains example.com."
