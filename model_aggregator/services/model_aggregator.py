from __future__ import annotations

import base64
import re
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable
from urllib.parse import quote

import requests

from model_aggregator.config import SETTINGS
from model_aggregator.services.benchmark import (
    BENCHMARK_TASKS,
    MAX_BENCHMARK_CASES,
    MAX_BENCHMARK_MODELS,
    MAX_BENCHMARK_RUNS,
    build_chat_payload,
    build_image_payload,
    case_attachment_ids,
    case_reference,
    case_source_text,
    normalize_benchmark_cases,
    public_task_catalog,
    score_against_reference,
    summarize_task_rows,
)
from model_aggregator.services.model_registry import (
    SUPPORTED_TASK_TYPES,
    ModelProfile,
    build_model_profiles,
    find_model_profile,
    translation_zh_en_guide,
)
from model_aggregator.services.task_router import (
    RouteDecision,
    is_auto_model_ref,
    normalize_task_type,
    select_model_for_payload,
)


def _compact_error(response: requests.Response) -> str:
    body = response.text.strip()
    if len(body) > 600:
        body = f"{body[:600]}..."
    return f"HTTP {response.status_code}: {body or response.reason}"


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _path_candidates(path: str, fallback: str) -> list[str]:
    paths = [path or fallback, fallback]
    if fallback.startswith("/v1/"):
        paths.append(fallback.removeprefix("/v1"))
    return list(dict.fromkeys(item for item in paths if item))


def _extract_model_id(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, dict):
        return None
    for key in ("id", "name", "model"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return None


def _parse_models(payload: Any) -> list[str]:
    if isinstance(payload, list):
        source_items = payload
    elif isinstance(payload, dict):
        source_items = payload.get("data") or payload.get("models") or payload.get("items") or []
    else:
        source_items = []
    models = [_extract_model_id(item) for item in source_items]
    return list(dict.fromkeys(item for item in models if item))


def _parse_gemini_models(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    models = payload.get("models") or []
    items: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        generation_methods = item.get("supportedGenerationMethods") or []
        if not name.startswith("models/gemini"):
            continue
        if "generateContent" not in generation_methods:
            continue
        model_id = name.removeprefix("models/").strip()
        if model_id:
            items.append(model_id)
    items = [model for model in items if model != "gemini-2.5-flash"]
    for model in ("gemini-3.6-flash", "gemini-3.8-flash"):
        if model not in items:
            items.append(model)
    return list(dict.fromkeys(items))


def _resolve_api_key(payload: dict[str, Any]) -> str:
    return str(payload.get("apiKey") or SETTINGS.model_tester_api_key or "").strip()


def _resolve_base_url(payload: dict[str, Any]) -> str:
    return str(payload.get("baseUrl") or SETTINGS.model_tester_base_url or "").strip().rstrip("/")


def _normalize_provider_preset(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "all": "all",
        "unified": "all",
        "local": "openai-compatible",
        "openai": "openai-compatible",
        "openai-compatible": "openai-compatible",
        "gemini": "gemini",
        "google-gemini": "gemini",
        "yunwu": "yunwu-gpt55",
        "yunwu-openai": "yunwu-gpt55",
        "yunwu-gpt55": "yunwu-gpt55",
        "mathpix": "mathpix",
        "mathpix-api": "mathpix",
    }
    return aliases.get(normalized, normalized or "openai-compatible")


def _provider_prefix(provider: str) -> str:
    if provider == "gemini":
        return "gemini"
    if provider == "yunwu-gpt55":
        return "yunwu"
    if provider == "mathpix":
        return "mathpix"
    return "local"


def _qualified_model_id(provider: str, model: str) -> str:
    return f"{_provider_prefix(provider)}:{model}"


def _parse_model_ref(model_ref: str, fallback_provider: str) -> tuple[str, str]:
    raw = model_ref.strip()
    if ":" not in raw:
        return fallback_provider, raw

    prefix, model = raw.split(":", 1)
    provider = {
        "local": "openai-compatible",
        "openai": "openai-compatible",
        "gemini": "gemini",
        "yunwu": "yunwu-gpt55",
        "mathpix": "mathpix",
    }.get(prefix.strip().lower())
    if provider and model.strip():
        return provider, model.strip()
    return fallback_provider, raw


def _model_hint_type(model: str) -> str:
    lowered = model.lower()
    if "embed" in lowered:
        return "embedding"
    if "gemini" in lowered or "gpt-5.5" in lowered or "mathpix" in lowered:
        return "vision_verified"
    if any(token in lowered for token in ("vl", "vision", "qwen-vl", "llava", "minicpm-v")):
        return "vision_verified"
    if any(token in lowered for token in ("medgemma", "gemma4", "qwen3.6")):
        return "vision_possible"
    return "text_only"


def _is_image_capable_model(model: str) -> bool:
    return _model_hint_type(model) in {"vision_verified", "vision_possible"}


def _is_ocr_candidate_model(model: str, allow_possible: bool = False) -> bool:
    lowered = model.lower()
    if any(token in lowered for token in ("embed", "tts", "robotics", "computer-use")):
        return False
    hint_type = _model_hint_type(model)
    return hint_type == "vision_verified" or (allow_possible and hint_type == "vision_possible")


def _image_markdown_timeout(provider: str) -> float:
    configured = max(1.0, SETTINGS.ocr_correction_timeout_seconds)
    if provider == "gemini":
        return max(1.0, SETTINGS.image_markdown_gemini_timeout_seconds)
    if provider == "yunwu-gpt55":
        return max(1.0, SETTINGS.image_markdown_yunwu_timeout_seconds)
    if provider == "mathpix":
        return min(max(1.0, SETTINGS.mathpix_timeout_seconds), 90)
    return configured


def _image_markdown_max_tokens(payload: dict[str, Any]) -> int:
    explicit = payload.get("maxTokens")
    if explicit not in (None, ""):
        return int(explicit)
    return max(8192, SETTINGS.ocr_correction_max_output_tokens)


def _gemini_image_key_attempt_order() -> list[tuple[int, str]]:
    return _gemini_key_attempt_order(limit=2)


def _extract_endpoint_config(base_url: str, models_path: str, chat_path: str) -> tuple[str, str, str]:
    normalized_base = base_url.rstrip("/")
    normalized_models_path = models_path or SETTINGS.model_tester_models_path
    normalized_chat_path = chat_path or SETTINGS.model_tester_chat_path

    if normalized_base.endswith("/chat/completions"):
        normalized_base = normalized_base[: -len("/chat/completions")]
        normalized_chat_path = "/chat/completions"
    elif normalized_base.endswith("/models"):
        normalized_base = normalized_base[: -len("/models")]
        normalized_models_path = "/models"

    return normalized_base, normalized_models_path, normalized_chat_path


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


OLLAMA_NATIVE_CHAT_MODELS = {
    "qwen3.6-27b:latest",
    "batiai/qwen3.6-27b:q4",
}


def _should_use_ollama_native_chat(provider: str, model: str) -> bool:
    return provider == "openai-compatible" and model.strip().lower() in OLLAMA_NATIVE_CHAT_MODELS


def _ollama_native_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[: -len("/v1")]
    return normalized


def _parse_data_url(data_url: str) -> tuple[str, str] | None:
    if not data_url.startswith("data:") or "," not in data_url:
        return None
    header, data = data_url.split(",", 1)
    mime_type = header[5:].split(";", 1)[0].strip() or "application/octet-stream"
    if ";base64" not in header:
        data = base64.b64encode(data.encode("utf-8")).decode("ascii")
    return mime_type, data


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:markdown|md)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else stripped


def _strip_internal_reasoning(text: str) -> str:
    cleaned = re.sub(r"<unused\d+>\s*thought\b.*?<unused\d+>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<think\b[^>]*>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"^\s*(?:thought|analysis)\s*[:：].*?(?=\n\n|\Z)", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


MATH_SPAN_PATTERN = re.compile(r"(\$\$.*?\$\$|\$[^$\n]*?\$)", flags=re.DOTALL)
BARE_INLINE_MATH_PATTERN = re.compile(
    r"\b([A-Za-z]\s*=\s*[-+]?(?:[A-Za-z]+|\d+(?:\.\d+)?)(?:\s*\^\s*(?:\{[^}\n]+\}|[A-Za-z0-9()+-]+))?)"
    r"(?=$|[\s,.;:|)\]])"
)


def _wrap_bare_inline_math(text: str) -> str:
    parts = MATH_SPAN_PATTERN.split(text)
    normalized: list[str] = []
    for part in parts:
        if not part:
            continue
        if MATH_SPAN_PATTERN.fullmatch(part):
            normalized.append(part)
            continue
        normalized.append(BARE_INLINE_MATH_PATTERN.sub(lambda match: f"${match.group(1)}$", part))
    return "".join(normalized)


def _normalize_inline_math(markdown: str) -> str:
    def normalize_cell(cell: str) -> str:
        stripped = cell.strip()
        if not stripped or re.fullmatch(r":?-{3,}:?", stripped):
            return cell
        return cell.replace(stripped, _wrap_bare_inline_math(stripped))

    lines: list[str] = []
    for line in markdown.splitlines():
        if "|" not in line:
            lines.append(_wrap_bare_inline_math(line))
            continue
        lines.append("|".join(normalize_cell(cell) for cell in line.split("|")))
    return "\n".join(lines).strip()


def _normalize_markdown_answer(text: str) -> str:
    return _normalize_inline_math(_strip_markdown_fence(_strip_internal_reasoning(text)))


def _clean_latex_text(value: str) -> str:
    text = value.strip()
    text = re.sub(r"(?:\\\\|\\)\s*$", "", text).strip()
    text = re.sub(r"\\\s*\$$", "$", text)
    text = re.sub(r"\\(?:displaystyle|textstyle|scriptstyle|scriptscriptstyle)\b\s*", "", text)
    text = text.replace(r"\&", "&")
    text = text.replace(r"\{", "{").replace(r"\}", "}")
    text = re.sub(r"\\backslash\b", r"\\", text)
    text = re.sub(r"\\left\s*", r"\\left", text)
    text = re.sub(r"\\right\s*", r"\\right", text)
    text = text.replace(r"\left", r"\left").replace(r"\right", r"\right")
    return re.sub(r"\s+", " ", text).strip()


def _balance_latex_cell_math(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    dollar_count = text.count("$")
    if dollar_count % 2 == 1:
        if text.startswith("$"):
            return f"{text}$"
        if text.endswith("$"):
            return f"${text}"
    if "$" not in text and re.search(r"\\[A-Za-z]+|[_^]\s*(?:\{|[A-Za-z0-9])", text):
        return f"${text}$"
    return text


def _latex_caption_to_text(match: re.Match[str]) -> str:
    return _clean_latex_text(match.group(1))


def _replace_latex_command_arg(text: str, command: str, replacer: Callable[[str], str]) -> str:
    marker = f"\\{command}{{"
    output: list[str] = []
    index = 0
    while True:
        start = text.find(marker, index)
        if start < 0:
            output.append(text[index:])
            break
        output.append(text[index:start])
        pos = start + len(marker)
        depth = 1
        while pos < len(text) and depth > 0:
            char = text[pos]
            previous = text[pos - 1] if pos > 0 else ""
            if char == "{" and previous != "\\":
                depth += 1
            elif char == "}" and previous != "\\":
                depth -= 1
            pos += 1
        if depth != 0:
            output.append(text[start:])
            break
        output.append(replacer(text[start + len(marker) : pos - 1]))
        index = pos
    return "".join(output)


def _markdown_table_from_tabular(match: re.Match[str]) -> str:
    body = match.group(2)
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"\\hline\b", "\n", body)
    raw_rows = []
    for line in body.split("\n"):
        line = line.strip()
        if "&" in line:
            raw_rows.extend(part for part in re.split(r"\\\\", line) if part.strip())
    rows: list[list[str]] = []
    for raw_row in raw_rows:
        row = raw_row.strip()
        if not row:
            continue
        cells = [_balance_latex_cell_math(_clean_latex_text(cell)) for cell in row.split("&")]
        if any(cells):
            rows.append(cells)

    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    lines = [
        "| " + " | ".join(normalized_rows[0]) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    for row in normalized_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _indent_fenced_code_blocks(markdown: str) -> str:
    def indent_block(match: re.Match[str]) -> str:
        language = match.group(1) or ""
        body = match.group(2)
        indent = 0
        formatted: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                formatted.append("")
                continue
            if re.fullmatch(r"end\b.*", line, flags=re.IGNORECASE):
                indent = max(0, indent - 1)
            formatted.append(f"{'  ' * indent}{line}")
            if re.match(r"for\b", line, flags=re.IGNORECASE):
                indent += 1
        return f"```{language}\n" + "\n".join(formatted).strip("\n") + "\n```"

    return re.sub(r"```([A-Za-z0-9_-]*)\n([\s\S]*?)\n```", indent_block, markdown)


def _normalize_mathpix_latex(markdown: str) -> str:
    text = markdown.strip()
    if not text:
        return ""
    text = text.replace(r"\{", "{").replace(r"\}", "}")
    text = text.replace(r"\&", "&")
    text = re.sub(r"\\backslash\b", r"\\", text)
    text = re.sub(r"(^|\n)\s*lbegin\{", r"\1\\begin{", text)
    text = re.sub(r"(^|\n)\s*lend\{", r"\1\\end{", text)
    text = re.sub(r"\\begin\{table\}", "", text)
    text = re.sub(r"\\end\{table\}", "", text)
    text = re.sub(r"(?m)^\s*}\s*$\n?", "", text)
    text = re.sub(r"\\captionsetup\{[^}]*\}", "", text)
    text = _replace_latex_command_arg(text, "caption", _clean_latex_text)
    text = re.sub(
        r"\\begin\{tabular\}\s*\{([^}]*)\}(.*?)\\end\{tabular\}",
        _markdown_table_from_tabular,
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r"(?m)^(\|.*\|)\s+}\s*$", r"\1", text)
    text = _indent_fenced_code_blocks(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_missing_image_answer(markdown: str) -> bool:
    normalized = re.sub(r"\s+", "", markdown.lower())
    if not normalized:
        return True
    missing_markers = (
        "请提供图片",
        "未提供图片",
        "没有提供图片",
        "无法看到图片",
        "无法识别图片",
        "没有图片",
        "上传图片",
        "needtheimage",
        "pleaseprovidetheimage",
        "noimage",
        "imageisnotprovided",
        "[请提供图片]",
    )
    if any(marker in normalized for marker in missing_markers):
        return True
    prompt_echo_markers = (
        "输出要求",
        "只输出markdown正文",
        "表格保持为markdowntable",
        "不要输出解释",
        "行内数学公式使用",
    )
    if "将图片中的文字转为markdown" in normalized and any(marker in normalized for marker in prompt_echo_markers):
        return True
    if normalized.startswith("输出要求") and any(marker in normalized for marker in prompt_echo_markers):
        return True
    if len(normalized) <= 40 and ("图片" in normalized or "image" in normalized):
        return True
    return False


def _image_to_markdown_system_prompt() -> str:
    return (
        "你是一个图片 OCR 到 Markdown 的转换器。只输出 Markdown，不解释过程。"
        "必须忠实识别图片中的文字、表格、数学公式和版面结构。"
        "必须完整输出整张图片的所有可见内容，不要只输出标题、摘要、开头几行或表头。"
        "如果图片里有长表格，必须逐行输出完整表格，直到最后一行；不要因为内容较多而提前停止。"
        "数学公式必须使用 $...$ 或 $$...$$，表格单元格中的公式也必须补齐美元符号。"
        "如果图片里有表格，优先输出标准 Markdown 表格。不要声称没有图片；如果看不清，只输出可辨认内容并用 [无法辨认] 标注。"
    )


def _image_to_markdown_user_text(prompt: str) -> str:
    user_prompt = prompt.strip() or "请将图片内容转换为 Markdown。"
    return (
        f"{user_prompt}\n\n"
        "输出要求：\n"
        "1. 只输出 Markdown 正文。\n"
        "2. 表格保持为 Markdown table。\n"
        "3. 表格必须包含所有可见行和列，不要省略数据行。\n"
        "4. 必须从图片顶部到图片底部完整转写，尤其不要停在第一张表格的表头或前几行。\n"
        "5. 行内数学公式使用 $...$，独立公式使用 $$...$$。\n"
        "6. 不要输出解释、前言或代码围栏。"
    )


def _trim_attachment_store() -> None:
    while len(ATTACHMENT_STORE) > 200:
        ATTACHMENT_STORE.popitem(last=False)


def _has_message_content(content: Any) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    return any(
        isinstance(item, dict)
        and (
            item.get("text")
            or item.get("image_url")
            or str(item.get("type") or "").strip() == "model_tester_attachment"
        )
        for item in content
    )


def _normalize_message_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, list):
        normalized: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip()
            if item_type == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    normalized.append({"type": "text", "text": text})
            elif item_type == "image_url":
                image_url = item.get("image_url")
                if isinstance(image_url, dict) and image_url.get("url"):
                    normalized.append({"type": "image_url", "image_url": {"url": str(image_url["url"])}})
            elif item_type == "model_tester_attachment":
                attachment_id = str(item.get("attachment_id") or "").strip()
                attachment = ATTACHMENT_STORE.get(attachment_id)
                if not attachment:
                    continue
                if attachment.get("kind") == "image" and attachment.get("data_url"):
                    normalized.append({"type": "image_url", "image_url": {"url": str(attachment["data_url"])}})
                elif attachment.get("kind") == "text" and attachment.get("text"):
                    normalized.append(
                        {
                            "type": "text",
                            "text": f"[附件: {attachment.get('name') or 'text'}]\n{attachment.get('text')}",
                        }
                    )
                else:
                    normalized.append(
                        {
                            "type": "text",
                            "text": (
                                f"[附件: {attachment.get('name') or 'file'}]\n"
                                f"文件类型: {attachment.get('mime_type') or attachment.get('kind') or 'unknown'}"
                            ),
                        }
                    )
        return normalized
    return str(content or "")


def _normalize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in messages[-30:]:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not _has_message_content(content):
            continue
        normalized.append(
            {
                "role": str(item.get("role") or "user"),
                "content": _normalize_message_content(content),
            }
        )
    return normalized


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n\n".join(
        str(item.get("text") or "").strip()
        for item in content
        if isinstance(item, dict) and str(item.get("type") or "").strip() == "text" and str(item.get("text") or "").strip()
    )


def _gemini_parts_from_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content.strip()}] if content.strip() else []
    if not isinstance(content, list):
        return []

    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type == "text":
            text = str(item.get("text") or "").strip()
            if text:
                parts.append({"text": text})
        elif item_type == "image_url":
            image_url = item.get("image_url")
            url = str(image_url.get("url") or "").strip() if isinstance(image_url, dict) else ""
            parsed = _parse_data_url(url)
            if parsed:
                mime_type, data = parsed
                parts.append({"inline_data": {"mime_type": mime_type, "data": data}})
            elif url:
                parts.append({"text": f"[image] {url}"})
    return parts


def _gemini_contents(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_lines: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if role == "system":
            text = _text_from_content(content)
            if text:
                system_lines.append(text)
            continue
        parts = _gemini_parts_from_content(content)
        if not parts:
            continue
        contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
    return "\n\n".join(system_lines).strip(), contents


def _provider_default_models(provider: str) -> list[str]:
    if provider == "gemini":
        return SETTINGS.gemini_models
    if provider == "yunwu-gpt55":
        return [SETTINGS.yunwu_gpt55_model] if SETTINGS.yunwu_gpt55_model else []
    if provider == "mathpix":
        return [SETTINGS.mathpix_model] if SETTINGS.mathpix_app_id and SETTINGS.mathpix_app_key and SETTINGS.mathpix_model else []
    return SETTINGS.model_tester_models


def _provider_config(provider: str) -> dict[str, Any]:
    if provider == "gemini":
        return {
            "id": "gemini",
            "label": "Gemini",
            "description": "使用后端环境变量中的 Gemini key 池轮值调用。",
            "baseUrl": SETTINGS.gemini_base_url,
            "modelsPath": "/v1beta/models",
            "chatPath": "/v1beta/models/{model}:generateContent",
            "defaultModels": SETTINGS.gemini_models,
            "configured": bool(SETTINGS.gemini_api_keys),
            "usesEnvKey": True,
            "keyStatusLabel": (
                f"使用后端 Gemini key 池（{len(SETTINGS.gemini_api_keys)} 个）"
                if SETTINGS.gemini_api_keys
                else "未配置 Gemini key 池"
            ),
        }
    if provider == "yunwu-gpt55":
        return {
            "id": "yunwu-gpt55",
            "label": "云雾 GPT-5.5",
            "description": "调用云雾侧的 GPT-5.5 环境变量配置。",
            "baseUrl": SETTINGS.yunwu_api_base_url,
            "modelsPath": "/v1/models",
            "chatPath": SETTINGS.yunwu_chat_path,
            "defaultModels": [SETTINGS.yunwu_gpt55_model] if SETTINGS.yunwu_gpt55_model else [],
            "configured": bool(SETTINGS.yunwu_api_base_url and SETTINGS.yunwu_api_key),
            "usesEnvKey": True,
            "keyStatusLabel": "使用后端云雾 API key" if SETTINGS.yunwu_api_key else "未配置云雾 API key",
        }
    if provider == "mathpix":
        return {
            "id": "mathpix",
            "label": "Mathpix",
            "description": "调用 Mathpix API 做数学 OCR / Markdown 识别。",
            "baseUrl": SETTINGS.mathpix_api_url,
            "modelsPath": "",
            "chatPath": "/v3/text",
            "defaultModels": [SETTINGS.mathpix_model] if SETTINGS.mathpix_app_id and SETTINGS.mathpix_app_key and SETTINGS.mathpix_model else [],
            "configured": bool(SETTINGS.mathpix_app_id and SETTINGS.mathpix_app_key),
            "usesEnvKey": True,
            "keyStatusLabel": "使用后端 Mathpix app_id/app_key" if SETTINGS.mathpix_app_key else "未配置 Mathpix API",
        }
    return {
        "id": "openai-compatible",
        "label": "OpenAI-compatible",
        "description": "兼容 OpenAI 的模型服务，可手动填写 Base URL 和临时 API key。",
        "baseUrl": SETTINGS.model_tester_base_url,
        "modelsPath": SETTINGS.model_tester_models_path,
        "chatPath": SETTINGS.model_tester_chat_path,
        "defaultModels": SETTINGS.model_tester_models,
        "configured": bool(SETTINGS.model_tester_base_url),
        "usesEnvKey": False,
        "keyStatusLabel": "使用后端环境变量 key" if SETTINGS.model_tester_api_key else "未配置默认 API key",
    }


def _resolve_openai_provider_config(payload: dict[str, Any], provider: str) -> tuple[str, str, str, str]:
    if provider == "yunwu-gpt55":
        return (
            str(payload.get("baseUrl") or SETTINGS.yunwu_api_base_url).rstrip("/"),
            str(payload.get("apiKey") or SETTINGS.yunwu_api_key or "").strip(),
            str(payload.get("model") or SETTINGS.yunwu_gpt55_model or "").strip(),
            str(payload.get("chatPath") or SETTINGS.yunwu_chat_path or "/v1/chat/completions"),
        )
    return (
        _resolve_base_url(payload),
        _resolve_api_key(payload),
        str(payload.get("model") or "").strip(),
        str(payload.get("chatPath") or SETTINGS.model_tester_chat_path),
    )


GEMINI_KEY_CURSOR = 0
GEMINI_KEY_COOLDOWNS: dict[str, float] = {}
GEMINI_RETRYABLE_STATUS_CODES = {401, 403, 429, 500, 502, 503, 504}
GEMINI_NETWORK_COOLDOWN_SECONDS = 15.0
GEMINI_DEFAULT_COOLDOWN_SECONDS = 60.0
GEMINI_AUTH_COOLDOWN_SECONDS = 300.0
GEMINI_MAX_COOLDOWN_SECONDS = 3600.0
GEMINI_KEY_COOLDOWN_STATUS_CODES = {401, 403, 429}


def _gemini_retry_delay_seconds(response: requests.Response) -> float | None:
    try:
        payload = response.json()
    except Exception:
        payload = {}

    details = payload.get("error", {}).get("details", []) if isinstance(payload, dict) else []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        retry_delay = str(detail.get("retryDelay") or "").strip()
        if retry_delay.endswith("s"):
            try:
                return float(retry_delay[:-1])
            except ValueError:
                pass

    match = re.search(r"retry\s+in\s+([0-9.]+)\s*s", response.text, flags=re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _gemini_cooldown_seconds(response: requests.Response | None = None) -> float:
    if response is None:
        return GEMINI_NETWORK_COOLDOWN_SECONDS
    if response.status_code in {401, 403}:
        return GEMINI_AUTH_COOLDOWN_SECONDS
    retry_delay = _gemini_retry_delay_seconds(response)
    if retry_delay is not None:
        return max(1.0, min(retry_delay, GEMINI_MAX_COOLDOWN_SECONDS))
    if response.status_code == 429:
        return GEMINI_DEFAULT_COOLDOWN_SECONDS
    return GEMINI_NETWORK_COOLDOWN_SECONDS


def _mark_gemini_key_cooling(api_key: str, response: requests.Response | None = None) -> None:
    until = time.monotonic() + _gemini_cooldown_seconds(response)
    GEMINI_KEY_COOLDOWNS[api_key] = max(GEMINI_KEY_COOLDOWNS.get(api_key, 0), until)


def _should_cool_gemini_key(response: requests.Response) -> bool:
    return response.status_code in GEMINI_KEY_COOLDOWN_STATUS_CODES


def _clear_gemini_key_cooling(api_key: str) -> None:
    GEMINI_KEY_COOLDOWNS.pop(api_key, None)


def _gemini_cooldown_message() -> str:
    now = time.monotonic()
    waits = [
        expires_at - now
        for key, expires_at in GEMINI_KEY_COOLDOWNS.items()
        if key in SETTINGS.gemini_api_keys and expires_at > now
    ]
    if not waits:
        return ""
    shortest_wait = max(1, int(min(waits) + 0.999))
    return f"所有 Gemini key 刚刚触发限流或临时错误，正在冷却；最短约 {shortest_wait} 秒后重试。"


def _gemini_key_attempt_order(limit: int | None = None) -> list[tuple[int, str]]:
    global GEMINI_KEY_CURSOR

    keys = SETTINGS.gemini_api_keys
    if not keys:
        return []
    start = GEMINI_KEY_CURSOR % len(keys)
    GEMINI_KEY_CURSOR = (start + 1) % len(keys)
    now = time.monotonic()
    attempts: list[tuple[int, str]] = []
    for offset in range(len(keys)):
        key_index = (start + offset) % len(keys)
        api_key = keys[key_index]
        if GEMINI_KEY_COOLDOWNS.get(api_key, 0) > now:
            continue
        attempts.append((key_index + 1, api_key))
        if limit is not None and len(attempts) >= limit:
            break
    return attempts


class ModelTesterService:
    def _model_profiles(self) -> list[ModelProfile]:
        return build_model_profiles(SETTINGS)

    def _route_task_type(self, payload: dict[str, Any]) -> str:
        return normalize_task_type(payload.get("taskType") or payload.get("mode"), payload)

    def _route_purpose(self, task_type: str) -> str:
        return "image-to-markdown" if task_type in {"ocr.image_to_markdown", "ocr.zh", "ocr.bo"} else "chat"

    def _router_config(self) -> dict[str, Any]:
        return {
            "autoModel": True,
            "defaultTaskType": "general.chat",
            "taskTypes": list(SUPPORTED_TASK_TYPES),
            "constraintKeys": [
                "prefer",
                "allowProviders",
                "denyProviders",
                "preferredProvider",
                "requireProvider",
                "requireLocal",
                "requireVision",
                "maxCostTier",
                "preferredModels",
                "denyModels",
            ],
        }

    def _benchmark_tasks(self, payload: dict[str, Any]) -> list[str]:
        raw_tasks = payload.get("tasks") or payload.get("taskTypes")
        if raw_tasks is None:
            raw_tasks = list(BENCHMARK_TASKS)
        if isinstance(raw_tasks, str):
            raw_tasks = [item.strip() for item in raw_tasks.split(",") if item.strip()]
        if not isinstance(raw_tasks, list):
            return []
        tasks: list[str] = []
        for item in raw_tasks:
            task_type = normalize_task_type(item)
            if task_type in BENCHMARK_TASKS and task_type not in tasks:
                tasks.append(task_type)
        return tasks

    def _benchmark_models(
        self,
        payload: dict[str, Any],
        profiles: list[ModelProfile],
    ) -> list[tuple[str, str, str, ModelProfile | None]]:
        explicit_models = payload.get("models") or payload.get("modelRefs")
        if isinstance(explicit_models, str):
            explicit_models = [item.strip() for item in explicit_models.split(",") if item.strip()]

        default_providers = {"openai-compatible", "gemini", "yunwu-gpt55"}
        raw_providers = payload.get("providers")
        if isinstance(raw_providers, str):
            raw_providers = [item.strip() for item in raw_providers.split(",") if item.strip()]
        providers = {
            _normalize_provider_preset(str(item))
            for item in (raw_providers if isinstance(raw_providers, list) else default_providers)
        }

        candidates: list[tuple[str, str, str, ModelProfile | None]] = []
        if isinstance(explicit_models, list) and explicit_models:
            fallback_provider = _normalize_provider_preset(str(payload.get("providerPreset") or "openai-compatible"))
            for raw_model in explicit_models:
                provider, model = _parse_model_ref(str(raw_model).strip(), fallback_provider)
                if not model:
                    continue
                model_ref = _qualified_model_id(provider, model)
                profile = find_model_profile(profiles, model_ref)
                item = (model_ref, provider, model, profile)
                if not any(existing[0] == model_ref for existing in candidates):
                    candidates.append(item)
        else:
            for profile in profiles:
                if profile.provider in providers and profile.available:
                    candidates.append((profile.id, profile.provider, profile.model, profile))

        return candidates[:MAX_BENCHMARK_MODELS]

    def benchmark(self, payload: dict[str, Any]) -> dict[str, Any]:
        started_at = time.perf_counter()
        tasks = self._benchmark_tasks(payload)
        if not tasks:
            return {
                "ok": False,
                "error": "请提供至少一个支持的 benchmark task。",
                "supportedTasks": public_task_catalog(),
            }

        profiles = self._model_profiles()
        selected_models = self._benchmark_models(payload, profiles)
        if not selected_models:
            return {
                "ok": False,
                "error": "没有找到可用于 benchmark 的已配置模型。",
                "defaultProviders": ["local", "gemini", "yunwu"],
            }

        try:
            requested_runs = int(payload.get("runs") or 1)
        except (TypeError, ValueError):
            requested_runs = 1
        try:
            requested_max_cases = int(payload.get("maxCases") or MAX_BENCHMARK_CASES)
        except (TypeError, ValueError):
            requested_max_cases = MAX_BENCHMARK_CASES
        runs = max(1, min(requested_runs, MAX_BENCHMARK_RUNS))
        max_cases = max(1, min(requested_max_cases, MAX_BENCHMARK_CASES))
        grouped_cases = normalize_benchmark_cases(
            payload.get("cases"),
            tasks,
            lambda value: normalize_task_type(value),
        )
        global_attachment_ids = payload.get("attachmentIds")
        include_answers = payload.get("includeAnswers", True) not in {False, 0, "0", "false", "False"}
        temperature = payload.get("temperature", 0)
        max_tokens = payload.get("maxTokens")
        result_profiles: list[dict[str, Any]] = []

        for model_ref, provider, model, profile in selected_models:
            task_results: list[dict[str, Any]] = []
            for task_type in tasks:
                cases = grouped_cases.get(task_type, [])[:max_cases]
                rows: list[dict[str, Any]] = []
                for run_index in range(runs):
                    for case in cases:
                        case_id = str(case.get("id") or "")
                        row: dict[str, Any] = {
                            "caseId": case_id if runs == 1 else f"{case_id}#run-{run_index + 1}",
                            "taskType": task_type,
                            "status": "pending",
                        }
                        if profile and not profile.available:
                            row.update({"status": "skipped", "error": "provider 未配置或当前不可用"})
                            rows.append(row)
                            continue
                        if profile and (
                            (BENCHMARK_TASKS[task_type]["operation"] == "chat" and not profile.chat_capable)
                            or (BENCHMARK_TASKS[task_type]["operation"] == "image-to-markdown" and not profile.image_capable)
                        ):
                            row.update({"status": "skipped", "error": "模型能力与该 benchmark task 不匹配"})
                            rows.append(row)
                            continue

                        if BENCHMARK_TASKS[task_type]["inputType"] == "text":
                            if not case_source_text(case):
                                row.update({"status": "failed", "error": "缺少 sourceText/input 文本"})
                                rows.append(row)
                                continue
                            request_payload = build_chat_payload(model_ref, task_type, case, temperature, max_tokens)
                            invoke = self.chat
                        else:
                            attachment_ids = case_attachment_ids(case, global_attachment_ids)
                            if not attachment_ids:
                                row.update({"status": "failed", "error": "缺少 attachmentIds 图片附件"})
                                rows.append(row)
                                continue
                            request_payload = build_image_payload(
                                model_ref,
                                task_type,
                                case,
                                temperature,
                                max_tokens,
                                global_attachment_ids,
                            )
                            invoke = self.image_to_markdown

                        case_started_at = time.perf_counter()
                        try:
                            response = invoke(request_payload)
                        except Exception as error:  # noqa: BLE001
                            response = {"ok": False, "error": str(error)}
                        elapsed_ms = round((time.perf_counter() - case_started_at) * 1000)
                        answer = str(response.get("answer") or response.get("markdown") or response.get("content") or "").strip()
                        ok = bool(response.get("ok")) and bool(answer)
                        row.update(
                            {
                                "status": "completed" if ok else "failed",
                                "latencyMs": response.get("latencyMs") if isinstance(response.get("latencyMs"), (int, float)) else elapsed_ms,
                                "provider": str(response.get("provider") or provider),
                                "model": str(response.get("model") or model),
                                "modelRef": str(response.get("modelRef") or model_ref),
                                "usage": response.get("usage"),
                            }
                        )
                        if not ok:
                            row["error"] = str(response.get("error") or "模型返回为空")
                        else:
                            score = score_against_reference(answer, case_reference(case))
                            row["score"] = score.get("score") if score else None
                            if score:
                                row["scoreDetails"] = score
                            if include_answers:
                                row["answer"] = answer[:1600]
                        rows.append(row)

                summary = summarize_task_rows(task_type, rows)
                summary["rows"] = rows
                task_results.append(summary)

            result_profiles.append(
                {
                    "modelRef": model_ref,
                    "provider": provider,
                    "model": model,
                    "staticProfile": profile.public_dict() if profile else None,
                    "tasks": task_results,
                }
            )

        completed_count = sum(
            task.get("completedCount", 0)
            for model_profile in result_profiles
            for task in model_profile.get("tasks", [])
        )
        return {
            "ok": completed_count > 0,
            "benchmarkRunId": uuid.uuid4().hex,
            "tasks": tasks,
            "models": [item[0] for item in selected_models],
            "providers": sorted({item[1] for item in selected_models}),
            "runs": runs,
            "maxCasesPerTask": max_cases,
            "includeAnswers": include_answers,
            "scoreNotice": "score 是基于 reference 的字符 F1 + 序列相似度，不替代人工翻译/OCR 质量评审。",
            "latencyMs": round((time.perf_counter() - started_at) * 1000),
            "profiles": result_profiles,
        }

    def route(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested_model = str(payload.get("model") or "auto").strip() or "auto"
        task_type = self._route_task_type(payload)
        purpose = self._route_purpose(task_type)
        profiles = self._model_profiles()

        if not is_auto_model_ref(requested_model):
            provider = _normalize_provider_preset(str(payload.get("providerPreset") or "openai-compatible"))
            provider, model = _parse_model_ref(requested_model, provider)
            if not model:
                return {"ok": False, "error": "请先选择一个模型。", "requestedModel": requested_model, "taskType": task_type}
            model_ref = _qualified_model_id(provider, model)
            profile = find_model_profile(profiles, model_ref)
            return {
                "ok": True,
                "purpose": purpose,
                "taskType": task_type,
                "requestedModel": requested_model,
                "selectedModel": model_ref,
                "resolvedModel": model_ref,
                "provider": provider,
                "model": model,
                "fallbacks": [],
                "reason": "已显式指定模型，未执行自动路由。",
                "routerDecision": {
                    "ok": True,
                    "manual": True,
                    "taskType": task_type,
                    "selectedModel": model_ref,
                    "provider": provider,
                    "model": model,
                    "reason": "已显式指定模型，未执行自动路由。",
                    "constraints": {},
                    "fallbacks": [],
                    "candidates": [],
                },
                "modelProfile": profile.public_dict() if profile else None,
            }

        decision = select_model_for_payload(payload, profiles, purpose=purpose)
        if not decision.ok or not decision.selected_model:
            return {
                "ok": False,
                "error": decision.reason,
                "purpose": purpose,
                "taskType": task_type,
                "requestedModel": requested_model,
                "selectedModel": None,
                "resolvedModel": None,
                "provider": None,
                "model": None,
                "fallbacks": [],
                "routerDecision": decision.public_dict(include_rejected=True),
            }

        profile = find_model_profile(profiles, decision.selected_model)
        public_decision = decision.public_dict(include_rejected=True)
        return {
            "ok": True,
            "purpose": purpose,
            "taskType": task_type,
            "requestedModel": requested_model,
            "selectedModel": decision.selected_model,
            "resolvedModel": decision.selected_model,
            "provider": decision.provider,
            "model": decision.model,
            "fallbacks": public_decision.get("fallbacks") or [],
            "reason": decision.reason,
            "routerDecision": public_decision,
            "modelProfile": profile.public_dict() if profile else None,
        }

    def config(self) -> dict[str, Any]:
        unified_models = self._fallback_unified_models()
        profiles = self._model_profiles()
        return {
            "ok": True,
            "baseUrl": SETTINGS.model_tester_base_url,
            "hasApiKey": bool(SETTINGS.model_tester_api_key),
            "modelsPath": SETTINGS.model_tester_models_path,
            "chatPath": SETTINGS.model_tester_chat_path,
            "defaultModels": SETTINGS.model_tester_models,
            "unifiedModels": unified_models,
            "defaultPreset": "openai-compatible",
            "router": self._router_config(),
            "modelProfiles": [profile.public_dict() for profile in profiles],
            "taskGuides": {
                "translation.zh_en": translation_zh_en_guide(),
            },
            "benchmark": {
                "tasks": public_task_catalog(),
                "defaultProviders": ["local", "gemini", "yunwu"],
                "maxCasesPerTask": MAX_BENCHMARK_CASES,
                "maxModels": MAX_BENCHMARK_MODELS,
                "maxRuns": MAX_BENCHMARK_RUNS,
                "scoreNotice": "score 是基于 reference 的字符 F1 + 序列相似度，不替代人工翻译/OCR 质量评审。",
            },
            "presets": [
                _provider_config("openai-compatible"),
                _provider_config("gemini"),
                _provider_config("yunwu-gpt55"),
                _provider_config("mathpix"),
            ],
        }

    def _fallback_unified_models(self) -> list[str]:
        items: list[str] = []
        items.extend(_qualified_model_id("openai-compatible", model) for model in SETTINGS.model_tester_models if model)
        items.extend(_qualified_model_id("gemini", model) for model in SETTINGS.gemini_models if model)
        if SETTINGS.yunwu_gpt55_model:
            items.append(_qualified_model_id("yunwu-gpt55", SETTINGS.yunwu_gpt55_model))
        if SETTINGS.mathpix_app_id and SETTINGS.mathpix_app_key and SETTINGS.mathpix_model:
            items.append(_qualified_model_id("mathpix", SETTINGS.mathpix_model))
        return list(dict.fromkeys(items))

    def _model_item(self, provider: str, model: str, source: str = "configured") -> dict[str, Any]:
        model_ref = _qualified_model_id(provider, model)
        profile = find_model_profile(self._model_profiles(), model_ref)
        if profile:
            item = profile.public_dict()
            item["source"] = source
        else:
            item = {
                "id": model_ref,
                "provider": provider,
                "providerPrefix": _provider_prefix(provider),
                "model": model,
                "label": f"{_provider_prefix(provider)}:{model}",
                "source": source,
                "imageCapable": _is_image_capable_model(model),
            }
        item["capability"] = _model_hint_type(model)
        item.setdefault("chatCapable", not any(token in model.lower() for token in ("embed", "embedding")))
        return item

    def _list_all_models(self, payload: dict[str, Any]) -> dict[str, Any]:
        providers = ("openai-compatible", "gemini", "yunwu-gpt55", "mathpix")
        items: list[str] = []
        model_items: list[dict[str, Any]] = []
        warnings: list[str] = []

        for provider in providers:
            provider_payload = dict(payload)
            provider_payload["providerPreset"] = provider
            result = self.list_models(provider_payload)
            if provider == "mathpix" and not result.get("ok"):
                if result.get("error"):
                    warnings.append(f"{_provider_prefix(provider)}: {result['error']}")
                continue
            for model in result.get("items") or []:
                model_id = _qualified_model_id(provider, str(model))
                if model_id in items:
                    continue
                items.append(model_id)
                model_items.append(self._model_item(provider, str(model), str(result.get("source") or "configured")))
            if not result.get("ok") and result.get("error"):
                warnings.append(f"{_provider_prefix(provider)}: {result['error']}")

        if not items:
            items = self._fallback_unified_models()
            model_items = [
                self._model_item(_parse_model_ref(model_id, "openai-compatible")[0], _parse_model_ref(model_id, "openai-compatible")[1])
                for model_id in items
            ]

        return {
            "ok": bool(items),
            "items": items,
            "modelItems": model_items,
            "source": "all-providers",
            "warning": "；".join(warnings),
        }

    def upload_attachment(self, payload: dict[str, Any]) -> dict[str, Any]:
        attachment_id = uuid.uuid4().hex
        name = str(payload.get("name") or "attachment").strip() or "attachment"
        kind = str(payload.get("kind") or "metadata").strip() or "metadata"
        item = {
            "id": attachment_id,
            "name": name,
            "kind": kind,
            "mime_type": str(payload.get("mimeType") or "").strip(),
            "size": int(payload.get("size") or 0),
            "created_at": time.time(),
        }
        if kind == "image":
            item["data_url"] = str(payload.get("dataUrl") or "")
        elif kind == "text":
            item["text"] = str(payload.get("text") or "")

        ATTACHMENT_STORE[attachment_id] = item
        _trim_attachment_store()
        return {
            "ok": True,
            "id": attachment_id,
            "name": item["name"],
            "kind": item["kind"],
            "mimeType": item["mime_type"],
            "size": item["size"],
        }

    def list_models(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = _normalize_provider_preset(str(payload.get("providerPreset") or "openai-compatible"))
        if provider == "all":
            return self._list_all_models(payload)
        if provider == "gemini":
            if not SETTINGS.gemini_api_keys:
                return {"ok": False, "items": SETTINGS.gemini_models, "source": "gemini-env", "error": "未配置 GEMINI_API_KEYS。"}

            errors: list[str] = []
            fallback_items = SETTINGS.gemini_models
            attempts = _gemini_key_attempt_order()
            if not attempts:
                return {
                    "ok": False,
                    "items": fallback_items,
                    "source": "gemini-env",
                    "error": _gemini_cooldown_message() or "Gemini key 池当前没有可用 key。",
                }
            for index, api_key in attempts:
                url = f"{SETTINGS.gemini_base_url}/v1beta/models?key={quote(api_key)}"
                try:
                    response = requests.get(url, timeout=SETTINGS.request_timeout_seconds)
                    if not response.ok:
                        errors.append(f"key#{index} -> {_compact_error(response)}")
                        if response.status_code not in GEMINI_RETRYABLE_STATUS_CODES:
                            break
                        _mark_gemini_key_cooling(api_key, response)
                        continue
                    models = _parse_gemini_models(response.json())
                    if models:
                        _clear_gemini_key_cooling(api_key)
                        return {"ok": True, "items": models, "source": "gemini-api"}
                    errors.append(f"key#{index} -> 响应里没有可识别的 Gemini 文本/多模态模型")
                except Exception as error:
                    errors.append(f"key#{index} -> {error}")
                    _mark_gemini_key_cooling(api_key)
            return {"ok": False, "items": fallback_items, "source": "gemini-env", "error": "；".join(errors) or "Gemini 模型列表请求失败。"}
        if provider == "yunwu-gpt55":
            models = [SETTINGS.yunwu_gpt55_model] if SETTINGS.yunwu_gpt55_model else []
            if not (SETTINGS.yunwu_api_base_url and SETTINGS.yunwu_api_key and models):
                return {"ok": False, "items": models, "source": "yunwu-env", "error": "未配置云雾 GPT-5.5 环境变量。"}
            return {"ok": True, "items": models, "source": "yunwu-env"}
        if provider == "mathpix":
            models = [SETTINGS.mathpix_model] if SETTINGS.mathpix_model else []
            if not (SETTINGS.mathpix_app_id and SETTINGS.mathpix_app_key and models):
                return {"ok": False, "items": [], "source": "mathpix-env", "error": "未配置 MATHPIX_APP_ID/MATHPIX_APP_KEY。"}
            return {"ok": True, "items": models, "source": "mathpix-env"}

        base_url = _resolve_base_url(payload)
        api_key = _resolve_api_key(payload)
        models_path = str(payload.get("modelsPath") or SETTINGS.model_tester_models_path)
        base_url, models_path, _ = _extract_endpoint_config(
            base_url,
            models_path,
            str(payload.get("chatPath") or SETTINGS.model_tester_chat_path),
        )

        if not base_url:
            return {
                "ok": True,
                "items": SETTINGS.model_tester_models,
                "source": "default",
                "warning": "未配置模型服务地址，已使用本地默认模型列表。",
            }

        errors: list[str] = []
        for path in _path_candidates(models_path, "/v1/models"):
            try:
                response = requests.get(
                    _join_url(base_url, path),
                    headers=_headers(api_key),
                    timeout=SETTINGS.request_timeout_seconds,
                )
                if not response.ok:
                    errors.append(f"{path} -> {_compact_error(response)}")
                    continue
                models = _parse_models(response.json())
                if models:
                    return {"ok": True, "items": models, "source": path}
                errors.append(f"{path} -> 响应里没有可识别的模型名称")
            except Exception as error:
                errors.append(f"{path} -> {error}")

        return {
            "ok": False,
            "items": SETTINGS.model_tester_models,
            "source": "default",
            "error": "；".join(errors) or "模型列表请求失败",
        }

    def _attach_chat_metadata(
        self,
        result: dict[str, Any],
        provider: str,
        model: str,
        requested_model: str,
        router_decision: RouteDecision | None = None,
    ) -> dict[str, Any]:
        response = dict(result)
        if model:
            model_ref = _qualified_model_id(provider, model)
            response.setdefault("model", model)
            response.setdefault("provider", provider)
            response.setdefault("modelRef", model_ref)
            response.setdefault("resolvedModel", model_ref)
        if router_decision:
            response["requestedModel"] = requested_model or "auto"
            response["fallbackUsed"] = False
            response["routerDecision"] = router_decision.public_dict(include_rejected=not router_decision.ok)
        return response

    def _route_chat_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], RouteDecision]:
        decision = select_model_for_payload(payload, self._model_profiles(), purpose="chat")
        if not decision.ok or not decision.selected_model:
            return payload, decision
        routed_payload = dict(payload)
        routed_payload["model"] = decision.selected_model
        routed_payload["providerPreset"] = decision.provider or routed_payload.get("providerPreset") or "openai-compatible"
        return routed_payload, decision

    def _chat_with_ollama_native(
        self,
        payload: dict[str, Any],
        model: str,
        messages: list[Any],
        base_url: str,
        api_key: str,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": float(payload.get("temperature", 0.7)),
        }
        max_tokens = payload.get("maxTokens")
        if max_tokens not in (None, ""):
            options["num_predict"] = int(max_tokens)
        top_p = payload.get("topP")
        if top_p not in (None, ""):
            options["top_p"] = float(top_p)

        request_body = {
            "model": model,
            "messages": _normalize_messages(messages),
            "stream": False,
            "think": bool(payload.get("enableThinking", False)),
            "options": options,
        }
        path = "/api/chat"
        started_at = time.perf_counter()
        try:
            response = requests.post(
                _join_url(_ollama_native_base_url(base_url), path),
                headers=_headers(api_key),
                json=request_body,
                timeout=SETTINGS.ocr_correction_timeout_seconds,
            )
            if not response.ok:
                return {"ok": False, "error": f"{path} -> {_compact_error(response)}"}

            data = response.json()
            message = data.get("message") if isinstance(data.get("message"), dict) else {}
            content = str(message.get("content") or "").strip()
            if not content:
                return {
                    "ok": False,
                    "error": "Ollama 原生接口返回成功，但正文为空。",
                    "path": path,
                    "latencyMs": round((time.perf_counter() - started_at) * 1000),
                }

            prompt_tokens = data.get("prompt_eval_count")
            completion_tokens = data.get("eval_count")
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
            if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
                usage["total_tokens"] = prompt_tokens + completion_tokens

            return {
                "ok": True,
                "answer": content,
                "reasoning": str(message.get("thinking") or "").strip(),
                "model": model,
                "path": path,
                "latencyMs": round((time.perf_counter() - started_at) * 1000),
                "usage": usage,
                "finishReason": data.get("done_reason"),
                "raw": data,
            }
        except Exception as error:
            return {"ok": False, "error": f"{path} -> {error}"}

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested_model = str(payload.get("model") or "").strip()
        router_decision: RouteDecision | None = None
        if is_auto_model_ref(requested_model):
            payload, router_decision = self._route_chat_payload(payload)
            if not router_decision.ok or not router_decision.selected_model:
                return self._attach_chat_metadata(
                    {"ok": False, "error": router_decision.reason},
                    "",
                    "",
                    requested_model,
                    router_decision,
                )

        provider = _normalize_provider_preset(str(payload.get("providerPreset") or "openai-compatible"))
        provider, model = _parse_model_ref(str(payload.get("model") or "").strip(), provider)
        resolved_model = model
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        if not model:
            return self._attach_chat_metadata({"ok": False, "error": "请先选择一个模型。"}, provider, model, requested_model, router_decision)
        if not messages:
            return self._attach_chat_metadata({"ok": False, "error": "请先输入一条消息。"}, provider, model, requested_model, router_decision)

        if provider == "gemini":
            return self._attach_chat_metadata(
                self._chat_with_gemini(payload, model, messages),
                provider,
                model,
                requested_model,
                router_decision,
            )

        base_url, api_key, model, chat_path = _resolve_openai_provider_config(payload, provider)
        model = resolved_model or model
        base_url, _, chat_path = _extract_endpoint_config(
            base_url,
            str(payload.get("modelsPath") or SETTINGS.model_tester_models_path),
            chat_path,
        )

        if not base_url:
            return self._attach_chat_metadata(
                {"ok": False, "error": "请先填写模型服务 Base URL，或设置后端环境变量。"},
                provider,
                model,
                requested_model,
                router_decision,
            )

        if _should_use_ollama_native_chat(provider, model):
            return self._attach_chat_metadata(
                self._chat_with_ollama_native(payload, model, messages, base_url, api_key),
                provider,
                model,
                requested_model,
                router_decision,
            )

        request_body: dict[str, Any] = {
            "model": model,
            "messages": _normalize_messages(messages),
            "temperature": float(payload.get("temperature", 0.7)),
            "stream": False,
        }
        max_tokens = payload.get("maxTokens")
        if max_tokens not in (None, ""):
            request_body["max_tokens"] = int(max_tokens)

        errors: list[str] = []
        started_at = time.perf_counter()
        for path in _path_candidates(chat_path, "/v1/chat/completions"):
            try:
                response = requests.post(
                    _join_url(base_url, path),
                    headers=_headers(api_key),
                    json=request_body,
                    timeout=SETTINGS.ocr_correction_timeout_seconds,
                )
                if not response.ok:
                    errors.append(f"{path} -> {_compact_error(response)}")
                    if response.status_code not in {404, 405}:
                        break
                    continue

                data = response.json()
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                content = str(message.get("content") or choice.get("text") or "").strip()
                reasoning = str(message.get("reasoning_content") or "").strip()
                return self._attach_chat_metadata(
                    {
                        "ok": True,
                        "answer": content,
                        "reasoning": reasoning,
                        "model": model,
                        "path": path,
                        "latencyMs": round((time.perf_counter() - started_at) * 1000),
                        "usage": data.get("usage"),
                        "finishReason": choice.get("finish_reason"),
                        "raw": data,
                    },
                    provider,
                    model,
                    requested_model,
                    router_decision,
                )
            except Exception as error:
                errors.append(f"{path} -> {error}")

        return self._attach_chat_metadata(
            {"ok": False, "error": "；".join(errors) or "模型请求失败"},
            provider,
            model,
            requested_model,
            router_decision,
        )

    def image_to_markdown(self, payload: dict[str, Any]) -> dict[str, Any]:
        attachment_ids = payload.get("attachmentIds") if isinstance(payload.get("attachmentIds"), list) else []
        image_attachments = self._resolve_image_attachments(attachment_ids)
        if not image_attachments:
            return {
                "ok": False,
                "error": "未找到已上传图片，请重新上传图片后再试。",
                "attempts": [],
            }

        prompt = str(payload.get("prompt") or payload.get("question") or "").strip()
        images = [str(item["data_url"]) for item in image_attachments if item.get("data_url")]
        candidates = self._image_markdown_candidates(payload)
        attempts: list[dict[str, Any]] = []
        started_at = time.perf_counter()

        for model_ref in candidates:
            provider, model = _parse_model_ref(model_ref, "openai-compatible")
            attempt = {
                "provider": provider,
                "model": model,
                "modelRef": _qualified_model_id(provider, model),
                "status": "pending",
            }
            attempts.append(attempt)
            allow_possible = payload.get("allowFallback") is False
            if not _is_ocr_candidate_model(model, allow_possible=allow_possible):
                attempt["status"] = "skipped"
                attempt["error"] = "该模型/通道未验证支持图片输入，已跳过图片 OCR 任务。手动勾选的实验性视觉模型会继续测试。"
                continue
            try:
                if provider == "gemini":
                    result = self._image_to_markdown_with_gemini(model, images, prompt, payload)
                elif provider == "mathpix":
                    result = self._image_to_markdown_with_mathpix(model, images, prompt, payload)
                else:
                    result = self._image_to_markdown_with_openai_compatible(provider, model, images, prompt, payload)
            except Exception as error:  # noqa: BLE001
                attempt["status"] = "error"
                attempt["error"] = str(error)
                continue

            markdown = _normalize_markdown_answer(str(result.get("markdown") or ""))
            if not markdown:
                attempt["status"] = "error"
                attempt["error"] = "模型返回为空。"
                attempt["raw"] = result.get("raw")
                continue
            if _looks_like_missing_image_answer(markdown):
                attempt["status"] = "error"
                attempt["error"] = "模型没有真正读取图片，可能当前本地接口未把 image_url 传入模型。"
                attempt["preview"] = markdown[:160]
                attempt["raw"] = result.get("raw")
                continue

            attempt["status"] = "done"
            attempt["latencyMs"] = result.get("latencyMs")
            return {
                "ok": True,
                "markdown": markdown,
                "answer": markdown,
                "provider": provider,
                "model": model,
                "modelRef": _qualified_model_id(provider, model),
                "path": result.get("path"),
                "latencyMs": round((time.perf_counter() - started_at) * 1000),
                "usage": result.get("usage"),
                "finishReason": result.get("finishReason"),
                "attempts": attempts,
                "raw": result.get("raw"),
            }

        if attempts and all(item.get("status") == "skipped" for item in attempts):
            error = "所选模型未验证支持图片输入。请改选 Gemini、云雾 GPT-5.5 或明确的视觉模型。"
        elif attempts and all("timed out" in str(item.get("error", "")).lower() for item in attempts if item.get("status") == "error"):
            error = "所选模型请求均超时。当前本地/远端生成接口响应较慢，请稍后重试或延长超时。"
        else:
            error = "所有图片转 Markdown 候选模型均失败。请检查 Gemini/云雾 key 额度，或确认本地视觉模型是否支持图片输入。"

        return {
            "ok": False,
            "error": error,
            "attempts": attempts,
        }

    def _resolve_image_attachments(self, attachment_ids: list[Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for raw_id in attachment_ids:
            attachment = ATTACHMENT_STORE.get(str(raw_id or "").strip())
            if not attachment:
                continue
            if attachment.get("kind") == "image" and attachment.get("data_url"):
                items.append(attachment)
        return items

    def _image_markdown_candidates(self, payload: dict[str, Any]) -> list[str]:
        explicit: list[str] = []
        if isinstance(payload.get("models"), list):
            explicit.extend(str(item).strip() for item in payload["models"] if str(item).strip())
        elif payload.get("model"):
            explicit.append(str(payload.get("model")).strip())

        if explicit and payload.get("allowFallback") is False:
            return list(dict.fromkeys(explicit))

        preferred: list[str] = []
        if SETTINGS.gemini_api_keys:
            preferred.extend(_qualified_model_id("gemini", model) for model in SETTINGS.gemini_models if _is_ocr_candidate_model(model))
        if SETTINGS.yunwu_api_base_url and SETTINGS.yunwu_api_key and SETTINGS.yunwu_gpt55_model:
            preferred.append(_qualified_model_id("yunwu-gpt55", SETTINGS.yunwu_gpt55_model))
        if SETTINGS.mathpix_app_id and SETTINGS.mathpix_app_key and SETTINGS.mathpix_model:
            preferred.append(_qualified_model_id("mathpix", SETTINGS.mathpix_model))

        local_defaults = [
            _qualified_model_id("openai-compatible", model)
            for model in SETTINGS.model_tester_models
            if _is_ocr_candidate_model(model)
        ]

        explicit_gemini = [item for item in explicit if item.startswith("gemini:")]
        explicit_yunwu = [item for item in explicit if item.startswith("yunwu:")]
        explicit_mathpix = [item for item in explicit if item.startswith("mathpix:")]
        explicit_local = [item for item in explicit if item.startswith("local:") or ":" not in item]
        return list(dict.fromkeys([*explicit_gemini, *preferred, *explicit_yunwu, *explicit_mathpix, *explicit_local, *local_defaults]))

    def _image_to_markdown_with_gemini(
        self,
        model: str,
        images: list[str],
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not SETTINGS.gemini_api_keys:
            raise RuntimeError("未配置 GEMINI_API_KEYS。")

        parts: list[dict[str, Any]] = [{"text": _image_to_markdown_user_text(prompt)}]
        for image in images:
            parsed = _parse_data_url(image)
            if not parsed:
                continue
            mime_type, data = parsed
            parts.append({"inline_data": {"mime_type": mime_type, "data": data}})
        if len(parts) == 1:
            raise RuntimeError("图片数据格式无效，无法发送给 Gemini。")

        request_body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "systemInstruction": {"parts": [{"text": _image_to_markdown_system_prompt()}]},
            "generationConfig": {
                "temperature": float(payload.get("temperature", 0)),
                "maxOutputTokens": _image_markdown_max_tokens(payload),
            },
        }
        encoded_model = quote(model.removeprefix("models/"), safe="")
        errors: list[str] = []
        started_at = time.perf_counter()
        attempts = _gemini_image_key_attempt_order()
        if not attempts:
            raise RuntimeError(_gemini_cooldown_message() or "Gemini key 池当前没有可用 key。")
        for index, api_key in attempts:
            url = f"{SETTINGS.gemini_base_url}/v1beta/models/{encoded_model}:generateContent?key={quote(api_key)}"
            try:
                response = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=request_body,
                    timeout=_image_markdown_timeout("gemini"),
                )
            except requests.RequestException as error:
                errors.append(f"key#{index} -> {error}")
                _mark_gemini_key_cooling(api_key)
                continue
            if not response.ok:
                errors.append(f"key#{index} -> {_compact_error(response)}")
                if response.status_code not in GEMINI_RETRYABLE_STATUS_CODES:
                    break
                if _should_cool_gemini_key(response):
                    _mark_gemini_key_cooling(api_key, response)
                continue
            data = response.json()
            candidates = data.get("candidates") or []
            candidate = candidates[0] if candidates else {}
            parts = candidate.get("content", {}).get("parts", []) if isinstance(candidate, dict) else []
            markdown = "\n".join(
                str(part.get("text") or "").strip()
                for part in parts
                if isinstance(part, dict) and str(part.get("text") or "").strip()
            )
            usage = data.get("usageMetadata") or {}
            _clear_gemini_key_cooling(api_key)
            return {
                "markdown": markdown,
                "path": "/v1beta/models/{model}:generateContent",
                "latencyMs": round((time.perf_counter() - started_at) * 1000),
                "usage": {
                    "prompt_tokens": usage.get("promptTokenCount"),
                    "completion_tokens": usage.get("candidatesTokenCount"),
                    "total_tokens": usage.get("totalTokenCount"),
                },
                "finishReason": candidate.get("finishReason") if isinstance(candidate, dict) else None,
                "raw": data,
            }
        raise RuntimeError("；".join(errors) or "Gemini 图片转 Markdown 请求失败。")

    def _image_to_markdown_with_mathpix(
        self,
        model: str,
        images: list[str],
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not SETTINGS.mathpix_app_id or not SETTINGS.mathpix_app_key:
            raise RuntimeError("未配置 MATHPIX_APP_ID/MATHPIX_APP_KEY。")
        if not images:
            raise RuntimeError("图片数据为空，无法发送给 Mathpix。")

        started_at = time.perf_counter()
        results: list[dict[str, Any]] = []
        chunks: list[str] = []
        for image in images:
            if not _parse_data_url(image):
                raise RuntimeError("图片数据格式无效，无法发送给 Mathpix。")
            request_body = {
                "src": image,
                "formats": ["text", "latex_styled", "data", "html"],
                "ocr": ["math", "text"],
                "skip_recrop": True,
                "math_inline_delimiters": ["$", "$"],
                "math_display_delimiters": ["$$", "$$"],
                "rm_spaces": False,
            }
            response = requests.post(
                SETTINGS.mathpix_api_url,
                headers={
                    "Content-Type": "application/json",
                    "app_id": SETTINGS.mathpix_app_id,
                    "app_key": SETTINGS.mathpix_app_key,
                },
                json=request_body,
                timeout=_image_markdown_timeout("mathpix"),
            )
            if not response.ok:
                raise RuntimeError(_compact_error(response))
            data = response.json()
            results.append(data)
            text = _normalize_mathpix_latex(str(data.get("latex_styled") or data.get("text") or "").strip())
            if text:
                chunks.append(text)

        return {
            "markdown": "\n\n".join(chunks).strip(),
            "path": SETTINGS.mathpix_api_url,
            "latencyMs": round((time.perf_counter() - started_at) * 1000),
            "usage": None,
            "finishReason": None,
            "raw": {"provider": "mathpix", "model": model, "results": results, "prompt": prompt},
        }

    def _image_to_markdown_with_openai_compatible(
        self,
        provider: str,
        model: str,
        images: list[str],
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        provider_payload = dict(payload)
        provider_payload["model"] = model
        base_url, api_key, model, chat_path = _resolve_openai_provider_config(provider_payload, provider)
        base_url, _, chat_path = _extract_endpoint_config(
            base_url,
            str(provider_payload.get("modelsPath") or SETTINGS.model_tester_models_path),
            chat_path,
        )
        if not base_url:
            raise RuntimeError("未配置 OpenAI-compatible Base URL。")

        user_content: list[dict[str, Any]] = [{"type": "text", "text": _image_to_markdown_user_text(prompt)}]
        user_content.extend({"type": "image_url", "image_url": {"url": image}} for image in images)
        request_body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": _image_to_markdown_system_prompt()},
                {"role": "user", "content": user_content},
            ],
            "temperature": float(payload.get("temperature", 0)),
            "max_tokens": _image_markdown_max_tokens(payload),
            "stream": False,
        }

        errors: list[str] = []
        started_at = time.perf_counter()
        for path in _path_candidates(chat_path, "/v1/chat/completions"):
            response = requests.post(
                _join_url(base_url, path),
                headers=_headers(api_key),
                json=request_body,
                timeout=_image_markdown_timeout(provider),
            )
            if not response.ok:
                errors.append(f"{path} -> {_compact_error(response)}")
                if response.status_code not in {404, 405}:
                    break
                continue
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            markdown = str(message.get("content") or choice.get("text") or "").strip()
            return {
                "markdown": markdown,
                "path": path,
                "latencyMs": round((time.perf_counter() - started_at) * 1000),
                "usage": data.get("usage"),
                "finishReason": choice.get("finish_reason"),
                "raw": data,
            }
        raise RuntimeError("；".join(errors) or "OpenAI-compatible 图片转 Markdown 请求失败。")

    def _chat_with_gemini(self, payload: dict[str, Any], model: str, messages: list[Any]) -> dict[str, Any]:
        if not SETTINGS.gemini_api_keys:
            return {"ok": False, "error": "未配置 GEMINI_API_KEYS。"}

        normalized_messages = _normalize_messages(messages)
        system_instruction, gemini_contents = _gemini_contents(normalized_messages)
        if not gemini_contents:
            return {"ok": False, "error": "Gemini 请求里没有可发送的消息内容。"}

        request_body: dict[str, Any] = {
            "contents": gemini_contents,
            "generationConfig": {
                "temperature": float(payload.get("temperature", 0.7)),
            },
        }
        if system_instruction:
            request_body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        max_tokens = payload.get("maxTokens")
        if max_tokens not in (None, ""):
            request_body["generationConfig"]["maxOutputTokens"] = int(max_tokens)

        started_at = time.perf_counter()
        errors: list[str] = []
        encoded_model = quote(model.removeprefix("models/"), safe="")
        attempts = _gemini_key_attempt_order()
        if not attempts:
            return {"ok": False, "error": _gemini_cooldown_message() or "Gemini key 池当前没有可用 key。"}
        for index, api_key in attempts:
            url = f"{SETTINGS.gemini_base_url}/v1beta/models/{encoded_model}:generateContent?key={quote(api_key)}"
            try:
                response = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=request_body,
                    timeout=SETTINGS.ocr_correction_timeout_seconds,
                )
                if not response.ok:
                    errors.append(f"key#{index} -> {_compact_error(response)}")
                    if response.status_code not in GEMINI_RETRYABLE_STATUS_CODES:
                        break
                    _mark_gemini_key_cooling(api_key, response)
                    continue

                data = response.json()
                candidates = data.get("candidates") or []
                candidate = candidates[0] if candidates else {}
                parts = candidate.get("content", {}).get("parts", []) if isinstance(candidate, dict) else []
                answer = "\n".join(
                    str(part.get("text") or "").strip()
                    for part in parts
                    if isinstance(part, dict) and str(part.get("text") or "").strip()
                ).strip()
                usage = data.get("usageMetadata") or {}
                usage_payload = {
                    "prompt_tokens": usage.get("promptTokenCount"),
                    "completion_tokens": usage.get("candidatesTokenCount"),
                    "total_tokens": usage.get("totalTokenCount"),
                }
                _clear_gemini_key_cooling(api_key)
                return {
                    "ok": True,
                    "answer": answer,
                    "reasoning": "",
                    "model": model,
                    "path": "/v1beta/models/{model}:generateContent",
                    "latencyMs": round((time.perf_counter() - started_at) * 1000),
                    "usage": usage_payload,
                    "finishReason": candidate.get("finishReason"),
                    "raw": data,
                }
            except Exception as error:
                errors.append(f"key#{index} -> {error}")
                _mark_gemini_key_cooling(api_key)

        return {"ok": False, "error": "；".join(errors) or "Gemini 请求失败"}

ATTACHMENT_STORE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
MODEL_TESTER_SERVICE = ModelTesterService()
