from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from model_aggregator.services.model_registry import ModelProfile, SUPPORTED_TASK_TYPES


TASK_ALIASES = {
    "chat": "general.chat",
    "general": "general.chat",
    "general.chat": "general.chat",
    "reader": "reader.explain",
    "reader.explain": "reader.explain",
    "explain": "reader.explain",
    "explanation": "reader.explain",
    "reader.translate": "reader.translate",
    "translate": "reader.translate",
    "translation": "reader.translate",
    "zh-en": "translation.zh_en",
    "zh_en": "translation.zh_en",
    "zh2en": "translation.zh_en",
    "zh.to.en": "translation.zh_en",
    "translation.zh-en": "translation.zh_en",
    "translation.zh_en": "translation.zh_en",
    "中译英": "translation.zh_en",
    "中文翻译英文": "translation.zh_en",
    "reader.summarize": "reader.summarize",
    "summarize": "reader.summarize",
    "summary": "reader.summarize",
    "code": "code.debug",
    "debug": "code.debug",
    "code.debug": "code.debug",
    "json": "structured.json",
    "structured": "structured.json",
    "structured.json": "structured.json",
    "ocr": "ocr.image_to_markdown",
    "image-to-markdown": "ocr.image_to_markdown",
    "image_markdown": "ocr.image_to_markdown",
    "ocr.image_to_markdown": "ocr.image_to_markdown",
    "zh-ocr": "ocr.zh",
    "zh_ocr": "ocr.zh",
    "cn-ocr": "ocr.zh",
    "ocr.zh": "ocr.zh",
    "ocr.zh_cn": "ocr.zh",
    "ocr.chinese": "ocr.zh",
    "中文ocr": "ocr.zh",
    "中文 ocr": "ocr.zh",
    "bo-ocr": "ocr.bo",
    "bo_ocr": "ocr.bo",
    "tibetan-ocr": "ocr.bo",
    "ocr.bo": "ocr.bo",
    "ocr.tibetan": "ocr.bo",
    "藏文ocr": "ocr.bo",
    "藏文 ocr": "ocr.bo",
    "bo-zh": "translation.bo_zh",
    "bo_zh": "translation.bo_zh",
    "bo.to.zh": "translation.bo_zh",
    "tibetan-to-chinese": "translation.bo_zh",
    "translation.bo-zh": "translation.bo_zh",
    "translation.bo_zh": "translation.bo_zh",
    "藏译中": "translation.bo_zh",
    "藏文翻译中文": "translation.bo_zh",
    "compare": "compare.reasoning",
    "compare.reasoning": "compare.reasoning",
}

PROVIDER_ALIASES = {
    "local": "openai-compatible",
    "openai": "openai-compatible",
    "openai-compatible": "openai-compatible",
    "gemini": "gemini",
    "google-gemini": "gemini",
    "yunwu": "yunwu-gpt55",
    "yunwu-gpt55": "yunwu-gpt55",
    "mathpix": "mathpix",
}

COST_RANK = {"none": 0, "low": 1, "low-medium": 2, "medium": 3, "high": 4}
SPEED_RANK = {"slow": 1, "medium": 2, "fast": 3}
QUALITY_RANK = {"none": 0, "medium": 1, "medium-high": 2, "high": 3}


@dataclass(slots=True)
class RouteDecision:
    ok: bool
    task_type: str
    selected_model: str | None
    provider: str | None
    model: str | None
    reason: str
    constraints: dict[str, Any]
    candidates: list[dict[str, Any]]
    rejected: list[dict[str, Any]]

    def public_dict(self, include_rejected: bool = False) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "taskType": self.task_type,
            "selectedModel": self.selected_model,
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "constraints": self.constraints,
            "fallbacks": [item["modelRef"] for item in self.candidates[1:5]],
            "candidates": self.candidates[:5],
        }
        if include_rejected:
            payload["rejected"] = self.rejected[:8]
        return payload


def is_auto_model_ref(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"auto", "router:auto", "task:auto", "auto:best"}


def normalize_task_type(value: Any, payload: dict[str, Any] | None = None) -> str:
    raw = str(value or "").strip().lower()
    if raw in TASK_ALIASES:
        return TASK_ALIASES[raw]
    if raw:
        normalized = raw.replace("_", ".").replace("-", ".")
        if normalized in SUPPORTED_TASK_TYPES:
            return normalized
        return "general.chat"

    payload = payload or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata_task = str(metadata.get("taskType") or metadata.get("task") or "").strip().lower()
    if metadata_task in TASK_ALIASES:
        return TASK_ALIASES[metadata_task]

    text = _message_text(payload)
    if re.search(r"(翻译|translate|translation)", text, flags=re.IGNORECASE):
        return "reader.translate"
    if re.search(r"(总结|摘要|summari[sz]e|summary)", text, flags=re.IGNORECASE):
        return "reader.summarize"
    if re.search(r"(代码|报错|debug|stack trace|traceback|exception)", text, flags=re.IGNORECASE):
        return "code.debug"
    if re.search(r"(json|schema|结构化|字段)", text, flags=re.IGNORECASE):
        return "structured.json"
    if re.search(r"(文献|论文|段落|原文|译文|解释|explain)", text, flags=re.IGNORECASE):
        return "reader.explain"
    return "general.chat"


def select_model_for_payload(
    payload: dict[str, Any],
    profiles: list[ModelProfile],
    purpose: str = "chat",
) -> RouteDecision:
    task_type = normalize_task_type(payload.get("taskType") or payload.get("mode"), payload)
    constraints = _constraints_from_payload(payload, task_type)
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for index, profile in enumerate(profiles):
        reject_reason = _reject_reason(profile, constraints, purpose, task_type)
        if reject_reason:
            rejected.append({"modelRef": profile.id, "provider": profile.provider, "reason": reject_reason})
            continue
        score = _score_profile(profile, task_type, constraints)
        if score <= 0:
            rejected.append({"modelRef": profile.id, "provider": profile.provider, "reason": "任务分数为 0"})
            continue
        candidates.append(_candidate_payload(profile, score, task_type, index))

    candidates.sort(key=lambda item: (-item["score"], item["rank"]))
    for item in candidates:
        item.pop("rank", None)

    if not candidates:
        return RouteDecision(
            ok=False,
            task_type=task_type,
            selected_model=None,
            provider=None,
            model=None,
            reason="没有满足当前任务和约束的可用模型。",
            constraints=constraints,
            candidates=[],
            rejected=rejected,
        )

    selected = candidates[0]
    return RouteDecision(
        ok=True,
        task_type=task_type,
        selected_model=str(selected["modelRef"]),
        provider=str(selected["provider"]),
        model=str(selected["model"]),
        reason=_selection_reason(selected, constraints),
        constraints=constraints,
        candidates=candidates,
        rejected=rejected,
    )


def _message_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    chunks: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "\n".join(chunks)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _string_set(value: Any) -> set[str]:
    if value is None or value == "":
        return set()
    if isinstance(value, str):
        items = re.split(r"[,\\s]+", value)
    elif isinstance(value, list | tuple | set):
        items = [str(item) for item in value]
    else:
        items = [str(value)]
    return {item.strip() for item in items if item.strip()}


def _provider_set(value: Any) -> set[str]:
    return {PROVIDER_ALIASES.get(item.lower(), item.lower()) for item in _string_set(value)}


def _constraints_from_payload(payload: dict[str, Any], task_type: str) -> dict[str, Any]:
    raw = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
    prefer = str(raw.get("prefer") or payload.get("prefer") or "quality").strip().lower()
    if prefer not in {"quality", "speed", "cost", "privacy", "balanced"}:
        prefer = "quality"

    allow_providers = _provider_set(raw.get("allowProviders") or raw.get("providers") or payload.get("allowProviders"))
    deny_providers = _provider_set(raw.get("denyProviders") or raw.get("avoidProviders") or payload.get("denyProviders"))
    preferred_provider = str(raw.get("preferredProvider") or payload.get("preferredProvider") or "").strip().lower()
    preferred_provider = PROVIDER_ALIASES.get(preferred_provider, preferred_provider)
    require_provider = str(raw.get("requireProvider") or payload.get("requireProvider") or "").strip().lower()
    require_provider = PROVIDER_ALIASES.get(require_provider, require_provider)

    require_local = _as_bool(raw.get("requireLocal") or payload.get("requireLocal"))
    require_vision = _as_bool(raw.get("requireVision") or payload.get("requireVision")) or task_type in {
        "ocr.image_to_markdown",
        "ocr.zh",
        "ocr.bo",
    }
    max_cost_tier = str(raw.get("maxCostTier") or raw.get("maxCost") or payload.get("maxCostTier") or "").strip().lower()

    return {
        "prefer": prefer,
        "allowProviders": sorted(allow_providers),
        "denyProviders": sorted(deny_providers),
        "preferredProvider": preferred_provider,
        "requireProvider": require_provider,
        "requireLocal": require_local,
        "requireVision": require_vision,
        "maxCostTier": max_cost_tier,
        "preferredModels": sorted(_string_set(raw.get("preferredModels") or payload.get("preferredModels"))),
        "denyModels": sorted(_string_set(raw.get("denyModels") or payload.get("denyModels"))),
    }


def _reject_reason(profile: ModelProfile, constraints: dict[str, Any], purpose: str, task_type: str) -> str | None:
    if not profile.available:
        return "provider 未配置或当前不可用"
    if purpose == "chat" and not profile.chat_capable:
        return "不是通用 chat 模型"
    if constraints["requireLocal"] and profile.provider != "openai-compatible":
        return "要求本地模型"
    if constraints["requireVision"] and not profile.image_capable:
        return "任务要求视觉能力"
    if constraints["requireProvider"] and profile.provider != constraints["requireProvider"]:
        return "不符合 requireProvider"
    allow_providers = set(constraints["allowProviders"])
    if allow_providers and profile.provider not in allow_providers:
        return "不在 allowProviders 中"
    if profile.provider in set(constraints["denyProviders"]):
        return "在 denyProviders 中"
    if profile.id in set(constraints["denyModels"]) or profile.model in set(constraints["denyModels"]):
        return "在 denyModels 中"
    max_cost_tier = constraints["maxCostTier"]
    if max_cost_tier and COST_RANK.get(profile.cost_tier, 99) > COST_RANK.get(max_cost_tier, 99):
        return "超过 maxCostTier"
    if task_type in {"ocr.image_to_markdown", "ocr.zh", "ocr.bo"} and not profile.image_capable:
        return "OCR 任务需要图片能力"
    return None


def _score_profile(profile: ModelProfile, task_type: str, constraints: dict[str, Any]) -> float:
    score = profile.score_for(task_type) * 100
    prefer = constraints["prefer"]
    if prefer == "quality":
        score += QUALITY_RANK.get(profile.quality_tier, 0) * 6
    elif prefer == "speed":
        score += SPEED_RANK.get(profile.speed_tier, 0) * 10
    elif prefer == "cost":
        score += max(0, 5 - COST_RANK.get(profile.cost_tier, 5)) * 8
    elif prefer == "privacy":
        score += 24 if profile.privacy == "local" else 0
    else:
        score += QUALITY_RANK.get(profile.quality_tier, 0) * 4
        score += SPEED_RANK.get(profile.speed_tier, 0) * 3
        score += max(0, 5 - COST_RANK.get(profile.cost_tier, 5)) * 3

    if constraints["preferredProvider"] and profile.provider == constraints["preferredProvider"]:
        score += 18
    preferred_models = set(constraints["preferredModels"])
    if profile.id in preferred_models or profile.model in preferred_models:
        score += 24
    return round(score, 2)


def _candidate_payload(profile: ModelProfile, score: float, task_type: str, index: int) -> dict[str, Any]:
    return {
        "modelRef": profile.id,
        "provider": profile.provider,
        "providerPrefix": profile.provider_prefix,
        "model": profile.model,
        "score": score,
        "taskScore": profile.score_for(task_type),
        "costTier": profile.cost_tier,
        "speedTier": profile.speed_tier,
        "qualityTier": profile.quality_tier,
        "privacy": profile.privacy,
        "strengths": list(profile.strengths[:4]),
        "limits": list(profile.limits[:3]),
        "rank": index,
    }


def _selection_reason(selected: dict[str, Any], constraints: dict[str, Any]) -> str:
    prefer = constraints["prefer"]
    return (
        f"按任务能力分数和 prefer={prefer} 选择 {selected['modelRef']}；"
        f"质量={selected['qualityTier']}，速度={selected['speedTier']}，成本={selected['costTier']}。"
    )
