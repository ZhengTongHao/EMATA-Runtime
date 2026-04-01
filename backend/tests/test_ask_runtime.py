import unittest

from app.ask_runtime import AskKnowledgeQaModule


class _StubTool:
    def __init__(self, callback):
        self._callback = callback

    def execute(self, payload, *, user=None):
        return self._callback(payload, user=user)


class AskKnowledgeQaModuleTestCase(unittest.TestCase):
    def test_grounded_answer_uses_top_five_reranked_contexts(self) -> None:
        captured = {}
        module = AskKnowledgeQaModule()
        items = [
            {
                "chunk_id": f"chunk-{index}",
                "title": f"Doc {index}",
                "snippet": f"报销额度规则 {index}",
                "matched_terms": ["报销", "额度"],
                "rerank_score": 0.95 - index * 0.05,
            }
            for index in range(6)
        ]

        def answer_generate(payload, *, user=None):
            del user
            captured["payload"] = payload
            return {"status": "success", "mode": "llm_rag", "answer": "标准报销额度是 3000 元。[1][2]"}

        tools = {
            "knowledge_search": _StubTool(lambda payload, user=None: {"items": items, "trace": {"backend_mode": "test"}}),
            "rerank": _StubTool(lambda payload, user=None: {"items": items, "mode": "test-rerank"}),
            "answer_generate": _StubTool(answer_generate),
        }

        result = module.handle_turn(
            session=None,
            message="报销的额度是多少",
            user=None,
            tools=tools,
        )

        self.assertEqual(captured["payload"]["mode"], "grounded")
        self.assertEqual(len(captured["payload"]["contexts"]), 5)
        self.assertEqual(result["outputs"][0]["data"]["answer_mode"], "grounded_rag")
        self.assertEqual(result["outputs"][0]["data"]["used_tools"], ["knowledge_search", "rerank", "answer_generate"])
        citation_outputs = [item for item in result["outputs"] if item["type"] == "citation"]
        self.assertEqual(len(citation_outputs), 5)
