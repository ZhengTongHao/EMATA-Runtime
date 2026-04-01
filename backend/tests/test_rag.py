import unittest
from unittest.mock import patch

import httpx

from app.rag import AnswerGenerationService, RerankProvider


class RagAdaptersTestCase(unittest.TestCase):
    def test_rerank_provider_calls_dashscope_reranks_api(self) -> None:
        provider = RerankProvider(
            base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            api_key="test-key",
            model="qwen3-rerank",
        )

        def fake_post(url, headers=None, json=None, timeout=None):
            self.assertEqual(url, "https://dashscope.aliyuncs.com/compatible-api/v1/reranks")
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            self.assertEqual(json["model"], "qwen3-rerank")
            self.assertEqual(json["query"], "报销的额度是多少")
            self.assertEqual(len(json["documents"]), 2)
            return httpx.Response(
                200,
                json={
                    "output": {
                        "results": [
                            {"index": 1, "relevance_score": 0.93},
                            {"index": 0, "relevance_score": 0.51},
                        ]
                    }
                },
                request=httpx.Request("POST", url),
            )

        with patch("app.rag.httpx.post", side_effect=fake_post):
            results = provider.rerank(
                query="报销的额度是多少",
                documents=["普通审批制度", "报销额度为 3000 元"],
            )

        self.assertEqual(results[0]["index"], 1)
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_answer_generation_service_can_generate_general_answer(self) -> None:
        service = AnswerGenerationService(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="test-key",
            model="qwen3.5-flash",
        )

        def fake_post(url, headers=None, json=None, timeout=None):
            self.assertEqual(url, "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
            self.assertEqual(json["model"], "qwen3.5-flash")
            self.assertEqual(json["messages"][0]["role"], "system")
            self.assertEqual(json["messages"][1]["role"], "user")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "多模态是指模型可以同时理解文本、图像等多种输入。"}}]},
                request=httpx.Request("POST", url),
            )

        with patch("app.rag.httpx.post", side_effect=fake_post):
            answer = service.generate_general_answer(question="多模态是什么")

        self.assertIn("多模态", answer)


if __name__ == "__main__":
    unittest.main()
