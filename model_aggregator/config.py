from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent


def _parse_model_list(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.startswith("["):
        parsed = json.loads(value)
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_local_env() -> None:
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env()


@dataclass(slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Model Aggregator Service")
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))

    model_tester_base_url: str = os.getenv("MODEL_TESTER_BASE_URL", os.getenv("LLM_BASE_URL", "")).rstrip("/")
    model_tester_api_key: str = os.getenv("MODEL_TESTER_API_KEY", os.getenv("LLM_API_KEY", ""))
    model_tester_models_path: str = os.getenv("MODEL_TESTER_MODELS_PATH", "/v1/models")
    model_tester_chat_path: str = os.getenv("MODEL_TESTER_CHAT_PATH", "/v1/chat/completions")
    model_tester_models: list[str] = None  # type: ignore[assignment]

    gemini_base_url: str = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
    gemini_api_keys: list[str] = None  # type: ignore[assignment]
    gemini_models: list[str] = None  # type: ignore[assignment]

    yunwu_api_base_url: str = os.getenv("YUNWU_API_BASE_URL", "").rstrip("/")
    yunwu_api_key: str = os.getenv("YUNWU_API_KEY", "")
    yunwu_gpt55_model: str = os.getenv("YUNWU_GPT55_MODEL", "gpt-5.5")
    yunwu_chat_path: str = os.getenv("YUNWU_CHAT_PATH", "/v1/chat/completions")

    mathpix_api_url: str = os.getenv("MATHPIX_API_URL", "https://api.mathpix.com/v3/text").rstrip("/")
    mathpix_app_id: str = os.getenv("MATHPIX_APP_ID", "")
    mathpix_app_key: str = os.getenv("MATHPIX_APP_KEY", "")
    mathpix_model: str = os.getenv("MATHPIX_MODEL", "mathpix-text")
    mathpix_timeout_seconds: float = float(os.getenv("MATHPIX_TIMEOUT_SECONDS", "60"))

    ocr_correction_timeout_seconds: float = float(os.getenv("OCR_CORRECTION_TIMEOUT_SECONDS", "90"))
    ocr_correction_max_output_tokens: int = int(os.getenv("OCR_CORRECTION_MAX_OUTPUT_TOKENS", "8192"))

    def __post_init__(self) -> None:
        if self.model_tester_models is None:
            self.model_tester_models = _parse_model_list(
                os.getenv(
                    "MODEL_TESTER_MODELS",
                    (
                        "qwen3.6-27b:latest,"
                        "batiai/qwen3.6-27b:q4,"
                        "medgemma:1.5-4b,"
                        "gemma4:e4b,"
                        "gemma2:27b,"
                        "qwen2.5:14b,"
                        "nomic-embed-text:latest,"
                        "llama3:latest"
                    ),
                )
            )
        if self.gemini_api_keys is None:
            self.gemini_api_keys = _parse_model_list(os.getenv("GEMINI_API_KEYS", ""))
        if self.gemini_models is None:
            self.gemini_models = _parse_model_list(
                os.getenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash,gemini-flash-latest")
            )

    def public_dict(self) -> dict[str, Any]:
        return {
            "appName": self.app_name,
            "modelTesterConfigured": bool(self.model_tester_base_url),
            "geminiConfigured": bool(self.gemini_api_keys),
            "yunwuConfigured": bool(self.yunwu_api_base_url and self.yunwu_api_key),
            "mathpixConfigured": bool(self.mathpix_app_id and self.mathpix_app_key),
        }


SETTINGS = Settings()
