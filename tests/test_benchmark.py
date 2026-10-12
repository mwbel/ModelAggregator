from __future__ import annotations

import unittest
from types import SimpleNamespace

from model_aggregator.services.benchmark import (
    BENCHMARK_TASKS,
    build_chat_payload,
    build_image_payload,
    public_task_catalog,
    score_against_reference,
    summarize_task_rows,
)
from model_aggregator.services.model_aggregator import ModelTesterService
from model_aggregator.services.model_registry import (
    ModelProfile,
    _gemini_profile,
    _local_profile,
    build_model_profiles,
    translation_zh_en_guide,
)
from model_aggregator.services.task_router import normalize_task_type, select_model_for_payload


class BenchmarkHelpersTest(unittest.TestCase):
    def test_gemini_31_flash_lite_profile_prefers_fast_translation(self) -> None:
        profile = _gemini_profile("gemini-3.1-flash-lite", "configured", True)
        self.assertEqual(profile.context_window, 1_048_576)
        self.assertEqual(profile.cost_tier, "low")
        self.assertEqual(profile.speed_tier, "fast")
        self.assertEqual(profile.task_scores["translation.zh_en"], 0.90)
        self.assertIn("批量初译", profile.strengths)

    def test_translation_guide_covers_seven_adapter_choices_and_evidence_boundary(self) -> None:
        guide = translation_zh_en_guide()
        adapter_ids = {item["adapterId"] for item in guide["recommendations"]}
        self.assertEqual(guide["profileVersion"], 2)
        self.assertEqual(guide["registryRevision"], "2026-10-11")
        self.assertEqual(guide["defaultAdapterModel"], "agg-gemini-3.8-flash")
        self.assertEqual(len(adapter_ids), 8)
        self.assertIn("agg-compare-all", adapter_ids)
        self.assertIn("尚无七模型", guide["benchmarkStatus"])
        flash_lite = next(item for item in guide["recommendations"] if item["adapterId"] == "agg-gemini-3.1-flash-lite")
        self.assertIn("1.29 秒", flash_lite["evidence"])
        self.assertIn("agg-gemini-31-flash-lite", flash_lite["legacyAdapterIds"])

    def test_translation_default_route_prefers_gemini_38_flash(self) -> None:
        gemini_38 = _gemini_profile("gemini-3.8-flash", "configured", True)
        flash_lite = _gemini_profile("gemini-3.1-flash-lite", "configured", True)
        qwen_36 = _local_profile("qwen3.6-27b:latest", "configured", True)
        profiles = [flash_lite, gemini_38, qwen_36]
        decision = select_model_for_payload(
            {"model": "auto", "taskType": "translation.zh_en", "constraints": {"prefer": "balanced"}},
            profiles,
            purpose="chat",
        )
        self.assertTrue(decision.ok)
        self.assertEqual(decision.selected_model, "gemini:gemini-3.8-flash")
        public_profile = gemini_38.public_dict()
        self.assertEqual(public_profile["profileVersion"], 2)
        self.assertEqual(public_profile["adapterId"], "agg-gemini-3.8-flash")

        cost_decision = select_model_for_payload(
            {"model": "auto", "taskType": "translation.zh_en", "constraints": {"prefer": "cost"}},
            profiles,
            purpose="chat",
        )
        self.assertEqual(cost_decision.selected_model, "gemini:gemini-3.1-flash-lite")

        privacy_decision = select_model_for_payload(
            {"model": "auto", "taskType": "translation.zh_en", "constraints": {"prefer": "privacy"}},
            profiles,
            purpose="chat",
        )
        self.assertEqual(privacy_decision.selected_model, "local:qwen3.6-27b:latest")

    def test_gemini_31_flash_lite_is_registered_with_older_configured_list(self) -> None:
        settings = SimpleNamespace(
            model_tester_base_url="",
            model_tester_models=[],
            gemini_api_keys=["configured"],
            gemini_models=["gemini-2.5-flash"],
            yunwu_gpt55_model="",
            mathpix_model="",
        )
        profile_ids = {profile.id for profile in build_model_profiles(settings)}
        self.assertIn("gemini:gemini-3.1-flash-lite", profile_ids)
        self.assertIn("gemini:gemini-3.6-flash", profile_ids)
        self.assertIn("gemini:gemini-3.8-flash", profile_ids)
        self.assertNotIn("gemini:gemini-2.5-flash", profile_ids)

    def test_task_aliases_cover_requested_workloads(self) -> None:
        self.assertEqual(normalize_task_type("中译英"), "translation.zh_en")
        self.assertEqual(normalize_task_type("中文OCR"), "ocr.zh")
        self.assertEqual(normalize_task_type("藏文 OCR"), "ocr.bo")
        self.assertEqual(normalize_task_type("藏译中"), "translation.bo_zh")

    def test_reference_score_is_bounded_and_exact_text_scores_one(self) -> None:
        result = score_against_reference("模型聚合服务", "模型聚合服务")
        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 1.0)

        partial = score_against_reference("模型服务", "模型聚合服务")
        self.assertGreater(partial["score"], 0)
        self.assertLess(partial["score"], 1)

    def test_payload_builders_keep_task_specific_instructions(self) -> None:
        chat_payload = build_chat_payload(
            "gemini:gemini-3.8-flash",
            "translation.zh_en",
            {"id": "case-1", "sourceText": "你好"},
            0,
            128,
        )
        self.assertIn("英文", chat_payload["messages"][0]["content"])
        self.assertIn("你好", chat_payload["messages"][1]["content"])
        self.assertEqual(chat_payload["maxTokens"], 128)

        image_payload = build_image_payload(
            "local:qwen3.6-27b:latest",
            "ocr.bo",
            {"id": "case-2", "attachmentIds": ["att-1"]},
            0,
            512,
        )
        self.assertIn("藏文", image_payload["prompt"])
        self.assertEqual(image_payload["attachmentIds"], ["att-1"])
        self.assertFalse(image_payload["allowFallback"])

    def test_catalog_exposes_all_requested_tasks(self) -> None:
        catalog_ids = {item["id"] for item in public_task_catalog()}
        self.assertEqual(catalog_ids, set(BENCHMARK_TASKS))


class BenchmarkServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ModelTesterService()
        self.profile = ModelProfile(
            id="local:test-model",
            provider="openai-compatible",
            provider_prefix="local",
            model="test-model",
            label="local:test-model",
            source="test",
            available=True,
            chat_capable=True,
            image_capable=True,
            supports_json=True,
            context_window=None,
            cost_tier="low",
            speed_tier="fast",
            quality_tier="medium",
            privacy="local",
            strengths=("test",),
            limits=(),
            task_scores={
                "translation.zh_en": 0.5,
                "ocr.zh": 0.5,
                "ocr.bo": 0.5,
                "translation.bo_zh": 0.5,
            },
        )
        self.service._model_profiles = lambda: [self.profile]

    def test_config_exposes_translation_task_guide(self) -> None:
        config = self.service.config()
        guide = config["taskGuides"]["translation.zh_en"]
        self.assertEqual(guide["defaultAdapterModel"], "agg-gemini-3.8-flash")
        self.assertEqual(guide["firstSelectionAdapterModel"], "agg-compare-all")

    def test_benchmark_returns_per_task_metrics_without_provider_call(self) -> None:
        def fake_chat(payload: dict[str, object]) -> dict[str, object]:
            return {
                "ok": True,
                "answer": "The model aggregation service reads keys only on the backend.",
                "provider": "openai-compatible",
                "model": "test-model",
                "modelRef": "local:test-model",
                "latencyMs": 120,
                "usage": {"completion_tokens": 12},
            }

        self.service.chat = fake_chat  # type: ignore[method-assign]
        result = self.service.benchmark(
            {
                "tasks": ["translation.zh_en"],
                "models": ["local:test-model"],
                "cases": [
                    {
                        "id": "case-1",
                        "taskType": "translation.zh_en",
                        "sourceText": "只在后端读取 key。",
                        "reference": "The model aggregation service reads keys only on the backend.",
                    }
                ],
            }
        )
        task = result["profiles"][0]["tasks"][0]
        self.assertTrue(result["ok"])
        self.assertEqual(task["completedCount"], 1)
        self.assertEqual(task["p50LatencyMs"], 120.0)
        self.assertEqual(task["p95LatencyMs"], 120.0)
        self.assertEqual(task["tokensPerSecond"], 100.0)
        self.assertEqual(task["rows"][0]["status"], "completed")

    def test_benchmark_reports_missing_ocr_attachment_as_failed(self) -> None:
        result = self.service.benchmark(
            {
                "tasks": ["ocr.zh"],
                "models": ["local:test-model"],
                "cases": [{"id": "case-1", "taskType": "ocr.zh", "reference": "中文"}],
            }
        )
        task = result["profiles"][0]["tasks"][0]
        self.assertFalse(result["ok"])
        self.assertEqual(task["errorRate"], 1.0)
        self.assertIn("attachmentIds", task["rows"][0]["error"])


class RouterTaskProfileTest(unittest.TestCase):
    def test_ocr_task_requires_vision_capability(self) -> None:
        text_only = ModelProfile(
            id="local:text-only",
            provider="openai-compatible",
            provider_prefix="local",
            model="text-only",
            label="local:text-only",
            source="test",
            available=True,
            chat_capable=True,
            image_capable=False,
            supports_json=True,
            context_window=None,
            cost_tier="low",
            speed_tier="fast",
            quality_tier="medium",
            privacy="local",
            strengths=(),
            limits=(),
            task_scores={"ocr.zh": 0.6},
        )
        decision = select_model_for_payload(
            {"model": "auto", "taskType": "ocr.zh", "messages": []},
            [text_only],
            purpose="image-to-markdown",
        )
        self.assertFalse(decision.ok)
        self.assertIn("视觉能力", decision.rejected[0]["reason"])


if __name__ == "__main__":
    unittest.main()
