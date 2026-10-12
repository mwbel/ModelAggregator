from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from model_aggregator.services.model_aggregator import ModelTesterService


class OllamaNativeChatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ModelTesterService()

    @patch("model_aggregator.services.model_aggregator.requests.post")
    def test_qwen36_uses_native_chat_with_thinking_disabled(self, post: Mock) -> None:
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "message": {"role": "assistant", "content": "OK"},
            "done_reason": "stop",
            "prompt_eval_count": 8,
            "eval_count": 2,
        }
        post.return_value = response

        result = self.service.chat(
            {
                "baseUrl": "http://ollama.test/v1",
                "model": "local:qwen3.6-27b:latest",
                "messages": [{"role": "user", "content": "只回复 OK"}],
                "temperature": 0,
                "maxTokens": 64,
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["answer"], "OK")
        self.assertEqual(result["path"], "/api/chat")
        self.assertEqual(result["resolvedModel"], "local:qwen3.6-27b:latest")
        self.assertEqual(result["usage"]["total_tokens"], 10)
        _, kwargs = post.call_args
        self.assertEqual(post.call_args.args[0], "http://ollama.test/api/chat")
        self.assertFalse(kwargs["json"]["think"])
        self.assertEqual(kwargs["json"]["options"]["num_predict"], 64)

    @patch("model_aggregator.services.model_aggregator.requests.post")
    def test_qwen36_q4_also_uses_native_chat(self, post: Mock) -> None:
        response = Mock()
        response.ok = True
        response.json.return_value = {"message": {"content": "OK"}, "done_reason": "stop"}
        post.return_value = response

        result = self.service.chat(
            {
                "baseUrl": "http://ollama.test/v1",
                "model": "local:batiai/qwen3.6-27b:q4",
                "messages": [{"role": "user", "content": "只回复 OK"}],
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(post.call_args.args[0], "http://ollama.test/api/chat")

    @patch("model_aggregator.services.model_aggregator.requests.post")
    def test_empty_native_response_is_reported_as_failure(self, post: Mock) -> None:
        response = Mock()
        response.ok = True
        response.json.return_value = {"message": {"content": ""}, "done_reason": "length"}
        post.return_value = response

        result = self.service.chat(
            {
                "baseUrl": "http://ollama.test/v1",
                "model": "local:qwen3.6-27b:latest",
                "messages": [{"role": "user", "content": "只回复 OK"}],
            }
        )

        self.assertFalse(result["ok"])
        self.assertIn("正文为空", result["error"])


if __name__ == "__main__":
    unittest.main()
