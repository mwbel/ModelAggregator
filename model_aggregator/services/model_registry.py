from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SUPPORTED_TASK_TYPES = (
    "general.chat",
    "reader.explain",
    "reader.translate",
    "reader.summarize",
    "code.debug",
    "structured.json",
    "ocr.image_to_markdown",
    "compare.reasoning",
    "translation.zh_en",
    "ocr.zh",
    "ocr.bo",
    "translation.bo_zh",
)

BUILTIN_GEMINI_MODELS = ("gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash")
MODEL_PROFILE_VERSION = 2
MODEL_REGISTRY_REVISION = "2026-10-11"

TRANSLATION_ZH_EN_RECOMMENDATIONS = (
    {
        "adapterId": "agg-gemini-3.8-flash",
        "legacyAdapterIds": [],
        "modelRef": "gemini:gemini-3.8-flash",
        "role": "formal-default",
        "label": "正式中翻英默认首选",
        "recommendation": "当前可用的高能力 Flash 型号，适合复杂任务；仍建议按实际语料评估。",
        "evidence": "基于官方模型定位的建议；尚无统一中英语料横向评分。",
        "default": True,
    },
    {
        "adapterId": "agg-gemini-3.6-flash",
        "legacyAdapterIds": [],
        "modelRef": "gemini:gemini-3.6-flash",
        "role": "quality-alternative",
        "label": "质量型备选",
        "recommendation": "可用于复杂任务与模型对照。",
        "evidence": "尚无统一中英语料横向评分。",
        "default": False,
    },
    {
        "adapterId": "agg-gemini-3.1-flash-lite",
        "legacyAdapterIds": ["agg-gemini-31-flash-lite"],
        "modelRef": "gemini:gemini-3.1-flash-lite",
        "role": "fast-batch",
        "label": "快速批量初译",
        "recommendation": "速度快、成本低，适合批量初译和短段落。",
        "evidence": "当前环境已有成功中翻英记录，单次记录约 1.29 秒。",
        "default": False,
    },
    {
        "adapterId": "agg-local-qwen3.6-27b",
        "legacyAdapterIds": ["agg-local-qwen36"],
        "modelRef": "local:qwen3.6-27b:latest",
        "role": "local-private",
        "label": "本地隐私翻译首选",
        "recommendation": "本地模型首选，适合隐私材料或不希望调用外部 API 的情况。",
        "evidence": "基于模型规模、部署方式和当前可调用状态的定位推荐。",
        "default": False,
    },
    {
        "adapterId": "agg-local-qwen3.6-27b-q4",
        "legacyAdapterIds": ["agg-local-qwen36-q4"],
        "modelRef": "local:batiai/qwen3.6-27b:q4",
        "role": "local-resource-saving",
        "label": "本地省资源初译",
        "recommendation": "更省资源，但量化可能损失措辞准确性，不建议作为终稿首选。",
        "evidence": "量化模型风险提示；尚无统一中英语料横向评分。",
        "default": False,
    },
    {
        "adapterId": "agg-local-qwen2.5-14b",
        "legacyAdapterIds": ["agg-local-qwen25"],
        "modelRef": "local:qwen2.5:14b",
        "role": "local-fallback",
        "label": "本地可用备选",
        "recommendation": "可用，但整体能力预计弱于 Qwen 3.6 27B。",
        "evidence": "基于模型代际和参数规模的保守预期；尚无统一中英语料横向评分。",
        "default": False,
    },
    {
        "adapterId": "agg-local-gemma2-27b",
        "legacyAdapterIds": ["agg-local-gemma2"],
        "modelRef": "local:gemma2:27b",
        "role": "comparison-baseline",
        "label": "本地对照模型",
        "recommendation": "可以作为对照，不是中文理解和中翻英的优先选择。",
        "evidence": "定位为对照项；尚无统一中英语料横向评分。",
        "default": False,
    },
    {
        "adapterId": "agg-compare-all",
        "legacyAdapterIds": [],
        "modelRef": None,
        "role": "comparison-tool",
        "label": "重要文稿首次选型",
        "recommendation": "同时比较各模型结果，不是单一翻译模型；首次处理重要材料时很有价值。",
        "evidence": "适配器侧多模型比较入口，不参与单模型自动路由。",
        "default": False,
    },
)


def translation_zh_en_guide() -> dict[str, Any]:
    return {
        "profileVersion": MODEL_PROFILE_VERSION,
        "registryRevision": MODEL_REGISTRY_REVISION,
        "taskType": "translation.zh_en",
        "defaultAdapterModel": "agg-gemini-3.8-flash",
        "defaultModelRef": "gemini:gemini-3.8-flash",
        "quickBatchAdapterModel": "agg-gemini-3.1-flash-lite",
        "localPrivateAdapterModel": "agg-local-qwen3.6-27b",
        "firstSelectionAdapterModel": "agg-compare-all",
        "benchmarkStatus": "尚无七模型使用同一组中英语料进行的完整横向评分。",
        "recommendationBasis": "默认建议基于官方模型定位；尚无统一中英语料横向评分。",
        "recommendations": [dict(item) for item in TRANSLATION_ZH_EN_RECOMMENDATIONS],
    }


def _translation_zh_en_profile(model_ref: str) -> dict[str, Any] | None:
    for item in TRANSLATION_ZH_EN_RECOMMENDATIONS:
        if item.get("modelRef") == model_ref:
            return dict(item)
    return None

PROVIDER_PREFIXES = {
    "openai-compatible": "local",
    "gemini": "gemini",
    "yunwu-gpt55": "yunwu",
    "mathpix": "mathpix",
}


@dataclass(slots=True)
class ModelProfile:
    id: str
    provider: str
    provider_prefix: str
    model: str
    label: str
    source: str
    available: bool
    chat_capable: bool
    image_capable: bool
    supports_json: bool
    context_window: int | None
    cost_tier: str
    speed_tier: str
    quality_tier: str
    privacy: str
    strengths: tuple[str, ...]
    limits: tuple[str, ...]
    task_scores: dict[str, float]
    task_score_basis: str = "capability-heuristic"

    def score_for(self, task_type: str) -> float:
        return self.task_scores.get(task_type, self.task_scores.get("general.chat", 0.0))

    def public_dict(self) -> dict[str, Any]:
        translation_profile = _translation_zh_en_profile(self.id)
        return {
            "id": self.id,
            "provider": self.provider,
            "providerPrefix": self.provider_prefix,
            "model": self.model,
            "label": self.label,
            "source": self.source,
            "available": self.available,
            "chatCapable": self.chat_capable,
            "imageCapable": self.image_capable,
            "supportsJson": self.supports_json,
            "contextWindow": self.context_window,
            "costTier": self.cost_tier,
            "speedTier": self.speed_tier,
            "qualityTier": self.quality_tier,
            "privacy": self.privacy,
            "strengths": list(self.strengths),
            "limits": list(self.limits),
            "taskScores": dict(self.task_scores),
            "taskScoreBasis": self.task_score_basis,
            "profileVersion": MODEL_PROFILE_VERSION,
            "registryRevision": MODEL_REGISTRY_REVISION,
            "adapterId": translation_profile.get("adapterId") if translation_profile else None,
            "legacyAdapterIds": translation_profile.get("legacyAdapterIds", []) if translation_profile else [],
            "translationZhEn": translation_profile,
        }


def provider_prefix(provider: str) -> str:
    return PROVIDER_PREFIXES.get(provider, "local")


def qualified_model_id(provider: str, model: str) -> str:
    return f"{provider_prefix(provider)}:{model}"


def _is_probably_image_capable(model: str) -> bool:
    lowered = model.lower()
    if any(token in lowered for token in ("vl", "vision", "qwen-vl", "llava", "minicpm-v")):
        return True
    return any(token in lowered for token in ("gemini", "gpt-5.5", "mathpix", "medgemma", "gemma4", "qwen3.6"))


def _is_embedding_model(model: str) -> bool:
    lowered = model.lower()
    return any(token in lowered for token in ("embed", "embedding", "nomic-embed"))


def _local_profile(model: str, source: str, available: bool) -> ModelProfile:
    lowered = model.lower()
    chat_capable = not _is_embedding_model(model)
    image_capable = _is_probably_image_capable(model)
    task_scores = {
        "general.chat": 0.55,
        "reader.explain": 0.58,
        "reader.translate": 0.50,
        "reader.summarize": 0.55,
        "code.debug": 0.52,
        "structured.json": 0.50,
        "ocr.image_to_markdown": 0.40 if image_capable else 0.0,
        "compare.reasoning": 0.55,
        "translation.zh_en": 0.52,
        "ocr.zh": 0.40 if image_capable else 0.0,
        "ocr.bo": 0.24 if image_capable else 0.0,
        "translation.bo_zh": 0.34,
    }
    strengths = ["本地私有", "低成本", "适合常规中文问答"]
    limits = ["质量依赖本地服务和模型版本", "长上下文与视觉能力需要实测确认"]
    quality_tier = "medium"
    speed_tier = "medium"
    context_window = None

    if "qwen3.6" in lowered or ("qwen" in lowered and "27b" in lowered):
        is_q4 = "q4" in lowered or "batiai/" in lowered
        task_scores.update(
            {
                "general.chat": 0.68,
                "reader.explain": 0.72,
                "reader.summarize": 0.66,
                "code.debug": 0.64,
                "structured.json": 0.62,
                "compare.reasoning": 0.68,
                "translation.zh_en": 0.66 if is_q4 else 0.72,
                "ocr.zh": 0.62 if image_capable else 0.0,
                "ocr.bo": 0.44 if image_capable else 0.0,
                "translation.bo_zh": 0.48,
            }
        )
        if is_q4:
            strengths = ["本地私有", "更省计算资源", "适合本地批量初译和对照"]
            limits = ["量化可能损失措辞准确性", "不建议作为正式译文终稿首选"]
        else:
            strengths = ["本地私有", "本地中翻英首选", "适合隐私材料和离线任务"]
            limits = ["质量仍需用正式语料复核", "复杂句终稿建议与高质量云模型对照"]
        quality_tier = "medium-high"
    elif "qwen2.5" in lowered:
        strengths = ["本地私有", "当前可用", "适合常规初译和兜底"]
        limits = ["整体能力预计弱于 Qwen 3.6 27B", "不建议作为重要终稿首选"]
        task_scores["translation.zh_en"] = 0.58
    elif "gemma" in lowered:
        strengths = ["本地私有", "响应成本低", "适合轻量问答"]
        task_scores.update(
            {
                "translation.zh_en": 0.56,
                "ocr.zh": 0.48 if image_capable else 0.0,
                "ocr.bo": 0.28 if image_capable else 0.0,
                "translation.bo_zh": 0.36,
            }
        )
        if "gemma2" in lowered:
            limits = ["可用于横向对照", "不是中文理解和中翻英的优先选择"]
    elif _is_embedding_model(model):
        chat_capable = False
        task_scores = {task_type: 0.0 for task_type in SUPPORTED_TASK_TYPES}
        strengths = ["向量检索/embedding"]
        limits = ["不适合作为 chat 生成模型"]
        quality_tier = "none"

    return ModelProfile(
        id=qualified_model_id("openai-compatible", model),
        provider="openai-compatible",
        provider_prefix="local",
        model=model,
        label=qualified_model_id("openai-compatible", model),
        source=source,
        available=available,
        chat_capable=chat_capable,
        image_capable=image_capable,
        supports_json=chat_capable,
        context_window=context_window,
        cost_tier="low",
        speed_tier=speed_tier,
        quality_tier=quality_tier,
        privacy="local",
        strengths=tuple(strengths),
        limits=tuple(limits),
        task_scores=task_scores,
    )


def _gemini_profile(model: str, source: str, available: bool) -> ModelProfile:
    lowered = model.lower()
    is_flash_lite = "flash-lite" in lowered
    is_gemini_36_flash = "gemini-3.6-flash" in lowered
    is_gemini_38_flash = "gemini-3.8-flash" in lowered
    task_scores = {
        "general.chat": 0.82,
        "reader.explain": 0.88,
        "reader.translate": 0.86,
        "reader.summarize": 0.84,
        "code.debug": 0.72,
        "structured.json": 0.82,
        "ocr.image_to_markdown": 0.88,
        "compare.reasoning": 0.78,
        "translation.zh_en": 0.91,
        "ocr.zh": 0.90,
        "ocr.bo": 0.80,
        "translation.bo_zh": 0.84,
    }
    if is_flash_lite:
        task_scores.update(
            {
                "reader.translate": 0.91,
                "translation.zh_en": 0.90,
            }
        )
    elif is_gemini_38_flash:
        task_scores.update(
            {
                "reader.translate": 0.94,
                "translation.zh_en": 0.95,
            }
        )
    elif is_gemini_36_flash:
        task_scores.update(
            {
                "reader.translate": 0.92,
                "translation.zh_en": 0.93,
            }
        )
    speed_tier = "fast" if "flash" in lowered else "medium"
    quality_tier = "high" if is_gemini_38_flash else "medium-high"
    context_window = 1_048_576 if any(version in lowered for version in ("3.1", "3.6", "3.8")) else None
    if is_flash_lite:
        strengths = ("批量初译", "短段落翻译", "低延迟", "低成本", "长上下文", "结构化输出")
    elif is_gemini_38_flash:
        strengths = ("复杂推理", "多步骤任务", "长上下文", "图片理解", "结构化输出")
    elif is_gemini_36_flash:
        strengths = ("长上下文", "复杂任务", "图片理解", "结构化输出")
    else:
        strengths = ("长上下文", "中文解释", "图片理解", "结构化输出", "延迟较低")
    return ModelProfile(
        id=qualified_model_id("gemini", model),
        provider="gemini",
        provider_prefix="gemini",
        model=model,
        label=qualified_model_id("gemini", model),
        source=source,
        available=available,
        chat_capable=True,
        image_capable=True,
        supports_json=True,
        context_window=context_window,
        cost_tier="low" if is_flash_lite else "low-medium",
        speed_tier=speed_tier,
        quality_tier=quality_tier,
        privacy="remote",
        strengths=strengths,
        limits=("需要 Gemini API key 和额度", "远端调用不适合敏感私有内容"),
        task_scores=task_scores,
    )


def _yunwu_profile(model: str, source: str, available: bool) -> ModelProfile:
    return ModelProfile(
        id=qualified_model_id("yunwu-gpt55", model),
        provider="yunwu-gpt55",
        provider_prefix="yunwu",
        model=model,
        label=qualified_model_id("yunwu-gpt55", model),
        source=source,
        available=available,
        chat_capable=True,
        image_capable=True,
        supports_json=True,
        context_window=None,
        cost_tier="high",
        speed_tier="medium",
        quality_tier="high",
        privacy="remote",
        strengths=("复杂推理", "代码和方案设计", "多模型对比基准", "高质量综合回答"),
        limits=("成本和延迟通常高于轻量模型", "需要云雾 API key 和额度"),
        task_scores={
            "general.chat": 0.88,
            "reader.explain": 0.88,
            "reader.translate": 0.80,
            "reader.summarize": 0.86,
            "code.debug": 0.88,
            "structured.json": 0.84,
            "ocr.image_to_markdown": 0.72,
            "compare.reasoning": 0.92,
            "translation.zh_en": 0.92,
            "ocr.zh": 0.84,
            "ocr.bo": 0.68,
            "translation.bo_zh": 0.78,
        },
    )


def _mathpix_profile(model: str, source: str, available: bool) -> ModelProfile:
    return ModelProfile(
        id=qualified_model_id("mathpix", model),
        provider="mathpix",
        provider_prefix="mathpix",
        model=model,
        label=qualified_model_id("mathpix", model),
        source=source,
        available=available,
        chat_capable=False,
        image_capable=True,
        supports_json=False,
        context_window=None,
        cost_tier="medium",
        speed_tier="medium",
        quality_tier="high",
        privacy="remote",
        strengths=("公式 OCR", "论文截图识别", "LaTeX/表格抽取"),
        limits=("不是通用 chat 模型", "需要 Mathpix app id/key"),
        task_scores={
            "general.chat": 0.0,
            "reader.explain": 0.0,
            "reader.translate": 0.0,
            "reader.summarize": 0.0,
            "code.debug": 0.0,
            "structured.json": 0.0,
            "ocr.image_to_markdown": 0.96,
            "compare.reasoning": 0.0,
            "translation.zh_en": 0.0,
            "ocr.zh": 0.90,
            "ocr.bo": 0.10,
            "translation.bo_zh": 0.0,
        },
    )


def build_model_profiles(settings: Any) -> list[ModelProfile]:
    profiles: list[ModelProfile] = []
    local_available = bool(getattr(settings, "model_tester_base_url", ""))
    for model in getattr(settings, "model_tester_models", []) or []:
        profiles.append(_local_profile(str(model), "configured", local_available))

    gemini_available = bool(getattr(settings, "gemini_api_keys", []))
    configured_gemini_models = [
        str(model) for model in (getattr(settings, "gemini_models", []) or [])
        if str(model).strip().removeprefix("gemini:") != "gemini-2.5-flash"
    ]
    gemini_models = list(dict.fromkeys([*configured_gemini_models, *BUILTIN_GEMINI_MODELS]))
    for model in gemini_models:
        profiles.append(_gemini_profile(str(model), "configured", gemini_available))

    yunwu_model = str(getattr(settings, "yunwu_gpt55_model", "") or "").strip()
    if yunwu_model:
        yunwu_available = bool(getattr(settings, "yunwu_api_base_url", "") and getattr(settings, "yunwu_api_key", ""))
        profiles.append(_yunwu_profile(yunwu_model, "configured", yunwu_available))

    mathpix_model = str(getattr(settings, "mathpix_model", "") or "").strip()
    if mathpix_model:
        mathpix_available = bool(getattr(settings, "mathpix_app_id", "") and getattr(settings, "mathpix_app_key", ""))
        profiles.append(_mathpix_profile(mathpix_model, "configured", mathpix_available))

    deduped: dict[str, ModelProfile] = {}
    for profile in profiles:
        deduped.setdefault(profile.id, profile)
    return list(deduped.values())


def find_model_profile(profiles: list[ModelProfile], model_ref: str) -> ModelProfile | None:
    normalized = model_ref.strip()
    for profile in profiles:
        if profile.id == normalized or profile.model == normalized:
            return profile
    return None
