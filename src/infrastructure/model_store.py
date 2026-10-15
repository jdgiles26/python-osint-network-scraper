"""Remember the model the user confirmed. The file holds no API key."""
import json
from pathlib import Path

from src.domain.inference import ModelConfig


def save_model_config(config: ModelConfig, path: str) -> None:
    payload = {
        "backend": config.backend,
        "model_id": config.model_id,
        "model_path": config.model_path,
        "endpoint": config.endpoint,
        "confirmed": bool(config.confirmed),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(target)


def load_model_config(path: str) -> ModelConfig | None:
    target = Path(path)
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    backend = str(payload.get("backend") or "").strip()
    if not backend:
        return None
    return ModelConfig(
        backend,
        str(payload.get("model_id") or ""),
        str(payload.get("model_path") or ""),
        str(payload.get("endpoint") or ""),
        confirmed=bool(payload.get("confirmed")),
    )
