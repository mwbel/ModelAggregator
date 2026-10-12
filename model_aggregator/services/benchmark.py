from __future__ import annotations

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from statistics import mean
from typing import Any, Callable


BENCHMARK_TASKS: dict[str, dict[str, Any]] = {
    "translation.zh_en": {
        "label": "中译英",
        "operation": "chat",
        "inputType": "text",
        "referenceRequired": True,
        "scoreMethod": "character_f1_sequence",
        "systemPrompt": (
            "你是专业的中译英译者。将输入的中文准确、自然地翻译成英文。"
            "只输出英文译文，不要解释、不要加引号、不要输出双语对照。"
        ),
        "promptPrefix": "请将下面的中文翻译成英文：\n",
        "strengths": ["现代中文到英文", "技术与说明文翻译", "术语保留能力"],
        "limits": ["参考答案评分是字符串相似度，不等同于人工语义评分"],
    },
    "ocr.zh": {
        "label": "中文 OCR",
        "operation": "image-to-markdown",
        "inputType": "image",
        "referenceRequired": True,
        "scoreMethod": "character_f1_sequence",
        "prompt": (
            "请只识别图片中的中文文字，保持原有阅读顺序、段落和标点。"
            "不要翻译，不要总结，不要解释；无法辨认的字符用 [无法辨认] 标记。"
        ),
        "strengths": ["中文印刷体识别", "段落与标点保留", "图片到 Markdown"],
        "limits": ["需要上传图片和参考文本才能计算识别分数"],
    },
    "ocr.bo": {
        "label": "藏文 OCR",
        "operation": "image-to-markdown",
        "inputType": "image",
        "referenceRequired": True,
        "scoreMethod": "character_f1_sequence",
        "prompt": (
            "请只识别图片中的藏文文字，保持原有阅读顺序、换行和标点。"
            "不要翻译成中文，不要总结，不要解释；无法辨认的字符用 [无法辨认] 标记。"
        ),
        "strengths": ["藏文字符识别", "行序与标点保留", "藏文原文提取"],
        "limits": ["字体、扫描质量和藏文排版会显著影响结果"],
    },
    "translation.bo_zh": {
        "label": "藏译中",
        "operation": "chat",
        "inputType": "text",
        "referenceRequired": True,
        "scoreMethod": "character_f1_sequence",
        "systemPrompt": (
            "你是专业的藏文译者。将输入的藏文准确、通顺地翻译成简体中文。"
            "只输出中文译文，不要解释、不要加引号、不要输出藏汉对照。"
        ),
        "promptPrefix": "请将下面的藏文翻译成简体中文：\n",
        "strengths": ["藏文到简体中文", "短段落翻译", "保留原文语义边界"],
        "limits": ["专业术语和古籍语境需要人工复核"],
    },
}

MAX_BENCHMARK_CASES = 32
MAX_BENCHMARK_MODELS = 24
MAX_BENCHMARK_RUNS = 3


def public_task_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": task_type,
            "label": definition["label"],
            "operation": definition["operation"],
            "inputType": definition["inputType"],
            "referenceRequired": definition["referenceRequired"],
            "scoreMethod": definition["scoreMethod"],
            "strengths": list(definition["strengths"]),
            "limits": list(definition["limits"]),
            "acceptedCaseFields": (
                ["sourceText", "input", "reference", "expected"]
                if definition["inputType"] == "text"
                else ["attachmentIds", "reference", "expected"]
            ),
        }
        for task_type, definition in BENCHMARK_TASKS.items()
    ]


def normalize_benchmark_cases(
    raw_cases: Any,
    tasks: list[str],
    normalize_task: Callable[[Any], str],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {task: [] for task in tasks}
    if isinstance(raw_cases, dict):
        for raw_task, items in raw_cases.items():
            task_type = normalize_task(raw_task)
            if task_type not in grouped or not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    grouped[task_type].append(dict(item))
    elif isinstance(raw_cases, list):
        for item in raw_cases:
            if not isinstance(item, dict):
                continue
            task_type = normalize_task(item.get("taskType") or item.get("task") or "")
            if task_type in grouped:
                grouped[task_type].append(dict(item))

    for task_type, items in grouped.items():
        for index, item in enumerate(items, start=1):
            item.setdefault("id", f"{task_type}-{index}")
            item["taskType"] = task_type
    return grouped


def case_source_text(case: dict[str, Any]) -> str:
    for key in ("sourceText", "input", "text", "content"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def case_reference(case: dict[str, Any]) -> str | None:
    for key in ("reference", "expected", "target"):
        value = case.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def case_attachment_ids(case: dict[str, Any], global_attachment_ids: Any = None) -> list[str]:
    raw = case.get("attachmentIds")
    if raw is None:
        raw = global_attachment_ids
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def build_chat_payload(
    model_ref: str,
    task_type: str,
    case: dict[str, Any],
    temperature: Any,
    max_tokens: Any,
) -> dict[str, Any]:
    definition = BENCHMARK_TASKS[task_type]
    source_text = case_source_text(case)
    user_text = f"{definition['promptPrefix']}{source_text}"
    payload: dict[str, Any] = {
        "model": model_ref,
        "taskType": task_type,
        "messages": [
            {"role": "system", "content": definition["systemPrompt"]},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0 if temperature in (None, "") else temperature,
        "metadata": {"benchmarkCaseId": str(case.get("id") or "")},
    }
    if max_tokens not in (None, ""):
        payload["maxTokens"] = max_tokens
    return payload


def build_image_payload(
    model_ref: str,
    task_type: str,
    case: dict[str, Any],
    temperature: Any,
    max_tokens: Any,
    global_attachment_ids: Any = None,
) -> dict[str, Any]:
    definition = BENCHMARK_TASKS[task_type]
    prompt = str(case.get("prompt") or definition["prompt"]).strip()
    payload: dict[str, Any] = {
        "model": model_ref,
        "models": [model_ref],
        "taskType": "ocr.image_to_markdown",
        "attachmentIds": case_attachment_ids(case, global_attachment_ids),
        "prompt": prompt,
        "allowFallback": False,
        "temperature": 0 if temperature in (None, "") else temperature,
        "metadata": {"benchmarkCaseId": str(case.get("id") or "")},
    }
    if max_tokens not in (None, ""):
        payload["maxTokens"] = max_tokens
    return payload


def metric_tokens(value: Any) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"```(?:markdown|md)?|```", "", text, flags=re.IGNORECASE)
    return [
        char
        for char in text
        if char.isalnum() or unicodedata.category(char).startswith("L") or "\u0f00" <= char <= "\u0fff"
    ]


def score_against_reference(answer: Any, reference: Any) -> dict[str, Any] | None:
    if reference is None or not str(reference).strip():
        return None
    answer_tokens = metric_tokens(answer)
    reference_tokens = metric_tokens(reference)
    if not reference_tokens:
        return {"score": 1.0 if not answer_tokens else 0.0, "precision": 1.0, "recall": 1.0, "sequence": 1.0}
    if not answer_tokens:
        return {"score": 0.0, "precision": 0.0, "recall": 0.0, "sequence": 0.0}

    answer_counts = Counter(answer_tokens)
    reference_counts = Counter(reference_tokens)
    overlap = sum((answer_counts & reference_counts).values())
    precision = overlap / len(answer_tokens)
    recall = overlap / len(reference_tokens)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    sequence = SequenceMatcher(None, answer_tokens, reference_tokens).ratio()
    score = 0.7 * f1 + 0.3 * sequence
    return {
        "score": round(score, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "sequence": round(sequence, 4),
    }


def usage_number(usage: Any, *keys: str) -> float | None:
    if not isinstance(usage, dict):
        return None
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 2)


def summarize_task_rows(task_type: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    scored = [row for row in completed if isinstance(row.get("score"), (int, float))]
    latencies = [float(row["latencyMs"]) for row in completed if isinstance(row.get("latencyMs"), (int, float))]
    completion_tokens = [
        number
        for row in completed
        for number in [usage_number(row.get("usage"), "completion_tokens", "completionTokens")]
        if number is not None
    ]
    tokens_per_second = [
        tokens / (float(row["latencyMs"]) / 1000)
        for row in completed
        for tokens in [usage_number(row.get("usage"), "completion_tokens", "completionTokens")]
        if tokens is not None and isinstance(row.get("latencyMs"), (int, float)) and float(row["latencyMs"]) > 0
    ]
    error_count = sum(row.get("status") == "failed" for row in rows)
    skipped_count = sum(row.get("status") == "skipped" for row in rows)
    return {
        "taskType": task_type,
        "label": BENCHMARK_TASKS[task_type]["label"],
        "operation": BENCHMARK_TASKS[task_type]["operation"],
        "caseCount": len(rows),
        "completedCount": len(completed),
        "scoredCaseCount": len(scored),
        "successRate": round(len(completed) / len(rows), 4) if rows else 0.0,
        "errorRate": round(error_count / len(rows), 4) if rows else 0.0,
        "skippedCount": skipped_count,
        "avgScore": round(mean(float(row["score"]) for row in scored), 4) if scored else None,
        "avgLatencyMs": round(mean(latencies), 2) if latencies else None,
        "p50LatencyMs": percentile(latencies, 0.50),
        "p95LatencyMs": percentile(latencies, 0.95),
        "avgCompletionTokens": round(mean(completion_tokens), 2) if completion_tokens else None,
        "tokensPerSecond": round(mean(tokens_per_second), 2) if tokens_per_second else None,
        "scoreMethod": BENCHMARK_TASKS[task_type]["scoreMethod"],
    }
