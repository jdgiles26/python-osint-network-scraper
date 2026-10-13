import os

from src.domain.inference import ModelConfig, validate_model_config


def test_gguf_backend_requires_existing_choice_not_a_download():
    missing = validate_model_config(ModelConfig("gguf_file", "", "", ""))
    assert missing.ok is False
    assert "path" in missing.error.lower()


def test_huggingface_id_is_accepted_without_downloading():
    result = validate_model_config(ModelConfig("huggingface", "org/model", "", ""))
    assert result.ok is True
    assert result.error == ""


def test_llama_cpp_is_valid_only_when_model_path_is_set(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("validation touched the filesystem or network")

    monkeypatch.setattr(os.path, "exists", _boom)
    ok = validate_model_config(ModelConfig("llama_cpp", "", "/models/foo.gguf", ""))
    assert ok.ok is True
    assert ok.error == ""
    missing = validate_model_config(ModelConfig("llama_cpp", "org/model", "", "http://127.0.0.1:8080"))
    assert missing.ok is False
    assert "path" in missing.error.lower()


def test_http_backends_need_an_http_endpoint():
    ok = validate_model_config(ModelConfig("ollama", "", "", "http://127.0.0.1:11434"))
    assert ok.ok is True
    missing = validate_model_config(ModelConfig("llamacpp_server", "model", "", "localhost"))
    assert missing.ok is False
    assert "endpoint" in missing.error.lower()
