from __future__ import annotations

import json
import mimetypes
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from model_aggregator.config import SETTINGS
from model_aggregator.services.model_aggregator import MODEL_TESTER_SERVICE


AGGREGATOR_HOST = os.getenv("AGGREGATOR_HOST", os.getenv("APP_HOST", "127.0.0.1"))
AGGREGATOR_PORT = int(os.getenv("AGGREGATOR_PORT", os.getenv("APP_PORT", "8890")))
SERVICE_NAME = os.getenv("AGGREGATOR_SERVICE_NAME", "Model Aggregator Service")
SERVICE_VERSION = "0.2.0"
API_PREFIX = "/api/aggregate"
ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    compact = dict(result)
    raw = compact.get("raw")
    if raw is not None:
        compact["rawPreview"] = str(raw)[:1200]
        compact.pop("raw", None)
    return compact


def _model_compare_payload(payload: dict[str, Any], model: str) -> dict[str, Any]:
    model_payload = dict(payload)
    model_payload["model"] = model
    model_payload.pop("models", None)
    return model_payload


def _compare(payload: dict[str, Any]) -> dict[str, Any]:
    models = payload.get("models") if isinstance(payload.get("models"), list) else []
    models = [str(model).strip() for model in models if str(model).strip()]
    if not models and payload.get("model"):
        models = [str(payload.get("model")).strip()]
    if not models:
        return {"ok": False, "error": "请提供 models 或 model。", "results": []}

    task_type = str(payload.get("taskType") or payload.get("mode") or "chat").strip().lower()
    is_image_markdown = task_type in {
        "image-to-markdown",
        "ocr",
        "image_markdown",
        "image-to-md",
        "ocr.zh",
        "ocr.bo",
    }
    results: list[dict[str, Any]] = []
    started_at = time.perf_counter()

    for model in models:
        model_payload = _model_compare_payload(payload, model)
        if is_image_markdown:
            model_payload["models"] = [model]
            model_payload.setdefault("allowFallback", False)
            result = MODEL_TESTER_SERVICE.image_to_markdown(model_payload)
        else:
            result = MODEL_TESTER_SERVICE.chat(model_payload)
        compact = _compact_result(result)
        resolved_model = compact.pop("model", None)
        results.append(
            {
                "model": model,
                "requestedModel": model,
                "resolvedModel": resolved_model or model,
                "ok": bool(result.get("ok")),
                "status": "completed" if result.get("ok") else "failed",
                **compact,
            }
        )

    return {
        "ok": any(item.get("ok") for item in results),
        "taskType": task_type if task_type in {"ocr.zh", "ocr.bo"} else ("image-to-markdown" if is_image_markdown else "chat"),
        "latencyMs": round((time.perf_counter() - started_at) * 1000),
        "results": results,
    }


class AggregatorHandler(BaseHTTPRequestHandler):
    server_version = f"ModelAggregatorHTTP/{SERVICE_VERSION}"

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith(API_PREFIX):
            self.send_response(HTTPStatus.OK)
            self._send_cors_headers()
            self.end_headers()
            return
        self._serve_static(parsed.path, head_only=True)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == f"{API_PREFIX}/health":
            self._send_json(
                {
                    "ok": True,
                    "service": SERVICE_NAME,
                    "version": SERVICE_VERSION,
                    "apiPrefix": API_PREFIX,
                    "appName": SETTINGS.app_name,
                }
            )
            return
        if parsed.path == f"{API_PREFIX}/config":
            self._send_json(
                {
                    **MODEL_TESTER_SERVICE.config(),
                    "service": SERVICE_NAME,
                    "version": SERVICE_VERSION,
                    "apiPrefix": API_PREFIX,
                    "endpoints": {
                        "health": f"{API_PREFIX}/health",
                        "config": f"{API_PREFIX}/config",
                        "models": f"{API_PREFIX}/models",
                        "upload": f"{API_PREFIX}/upload",
                        "route": f"{API_PREFIX}/route",
                        "benchmark": f"{API_PREFIX}/benchmark",
                        "chat": f"{API_PREFIX}/chat",
                        "imageToMarkdown": f"{API_PREFIX}/image-to-markdown",
                        "compare": f"{API_PREFIX}/compare",
                    },
                }
            )
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        payload = self._read_json()

        if parsed.path == f"{API_PREFIX}/models":
            self._send_json(MODEL_TESTER_SERVICE.list_models(payload))
            return
        if parsed.path in {f"{API_PREFIX}/upload", f"{API_PREFIX}/attachments"}:
            self._send_json(MODEL_TESTER_SERVICE.upload_attachment(payload))
            return
        if parsed.path == f"{API_PREFIX}/route":
            self._send_json(MODEL_TESTER_SERVICE.route(payload))
            return
        if parsed.path == f"{API_PREFIX}/benchmark":
            self._send_json(MODEL_TESTER_SERVICE.benchmark(payload))
            return
        if parsed.path == f"{API_PREFIX}/chat":
            self._send_json(MODEL_TESTER_SERVICE.chat(payload))
            return
        if parsed.path == f"{API_PREFIX}/image-to-markdown":
            self._send_json(MODEL_TESTER_SERVICE.image_to_markdown(payload))
            return
        if parsed.path == f"{API_PREFIX}/compare":
            self._send_json(_compare(payload))
            return

        self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        raw = self._read_body().decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def _read_body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return b""
        return self.rfile.read(content_length)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _serve_static(self, path: str, head_only: bool = False) -> None:
        relative_path = "index.html" if path in {"", "/"} else path.lstrip("/")
        file_path = (FRONTEND_DIR / relative_path).resolve()
        if FRONTEND_DIR not in file_path.parents and file_path != FRONTEND_DIR:
            self._send_json({"ok": False, "error": "Forbidden"}, status=HTTPStatus.FORBIDDEN)
            return
        if file_path.is_dir():
            file_path = file_path / "index.html"
        if not file_path.exists():
            self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        if path.startswith("/"):
            self._send_cors_headers()
        self.end_headers()
        if not head_only:
            self.wfile.write(content)


def run() -> None:
    server = ThreadingHTTPServer((AGGREGATOR_HOST, AGGREGATOR_PORT), AggregatorHandler)
    print(f"{SERVICE_NAME} running at http://{AGGREGATOR_HOST}:{AGGREGATOR_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
