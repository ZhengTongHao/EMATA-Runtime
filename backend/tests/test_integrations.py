import threading
import unittest
from unittest.mock import patch

import httpx

from app.integrations import (
    EmbeddingProvider,
    FeishuMcpClient,
    MilvusKnowledgeIndex,
    QueryRewriteService,
    TextGenerationProvider,
    TemporalRuntime,
)


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.mode = "deterministic"
        self.reason = "test"
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class FakeQueryRewriter:
    def __init__(self, variants=None) -> None:
        self._variants = variants or []
        self.calls = []

    def variants(self, query: str):
        self.calls.append(query)
        return self._variants or [query]


class FakeIndexParams:
    def __init__(self) -> None:
        self.indexes = []

    def add_index(self, **kwargs) -> None:
        self.indexes.append(kwargs)


class FakeMilvusClient:
    def __init__(self) -> None:
        self.collections = set()
        self.created = []
        self.loaded = []
        self.upserts = []
        self.search_calls = []
        self.search_results = []

    def has_collection(self, collection_name: str):
        return collection_name in self.collections

    def prepare_index_params(self):
        return FakeIndexParams()

    def create_collection(self, collection_name: str, schema, index_params) -> None:
        self.collections.add(collection_name)
        self.created.append(
            {
                "collection_name": collection_name,
                "schema": schema,
                "index_params": index_params.indexes,
            }
        )

    def load_collection(self, collection_name: str) -> None:
        self.loaded.append(collection_name)

    def upsert(self, collection_name: str, data):
        self.upserts.append({"collection_name": collection_name, "data": data})
        return {"upsert_count": len(data)}

    def search(self, collection_name: str, **kwargs):
        self.search_calls.append({"collection_name": collection_name, **kwargs})
        if self.search_results:
            return self.search_results.pop(0)
        return [[]]


class IntegrationAdaptersTestCase(unittest.TestCase):
    def test_embedding_provider_returns_stable_deterministic_vectors(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "EMATA_EMBEDDING_BASE_URL": "",
                "EMATA_EMBEDDING_API_KEY": "",
                "EMATA_MODEL_BASE_URL": "",
                "EMATA_MODEL_API_KEY": "",
            },
            clear=False,
        ):
            provider = EmbeddingProvider(base_url="", api_key="", vector_size=16)

            first = provider.embed_texts(["finance approval policy"])[0]
            second = provider.embed_texts(["finance approval policy"])[0]

            self.assertEqual(provider.mode, "deterministic")
            self.assertEqual(len(first), 16)
            self.assertEqual(first, second)

    def test_query_rewriter_keeps_original_and_adds_conservative_expansion(self) -> None:
        rewriter = QueryRewriteService()

        variants = rewriter.variants("ERP 审批 policy")

        self.assertEqual(variants[0], "ERP 审批 policy")
        self.assertTrue(any("enterprise resource planning" in item for item in variants[1:]))
        self.assertTrue(any("authorize" in item for item in variants[1:]))

    def test_text_generation_provider_calls_openai_compatible_chat_completions(self) -> None:
        provider = TextGenerationProvider(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="test-key",
            model="qwen3.5-flash",
        )

        def fake_post(url, headers=None, json=None, timeout=None):
            self.assertEqual(url, "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            self.assertEqual(json["model"], "qwen3.5-flash")
            self.assertEqual(json["messages"][0]["role"], "system")
            self.assertEqual(json["messages"][1]["role"], "user")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "根据报销制度，标准报销额度为 3000 元，超出部分需要额外审批。"
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

        with patch("app.integrations.httpx.post", side_effect=fake_post):
            answer = provider.generate_answer(
                question="报销的额度是多少",
                contexts=[
                    {
                        "title": "Finance Expense Policy",
                        "snippet": "报销标准额度为 3000 元，超过 3000 元需要财务额外审批。",
                    }
                ],
            )

        self.assertEqual(provider.mode, "openai-compatible")
        self.assertIn("3000", answer)

    def test_milvus_truncate_respects_utf8_byte_limit(self) -> None:
        value = "你" * 2000

        truncated = MilvusKnowledgeIndex._truncate(value, 4096)

        self.assertLessEqual(len(truncated.encode("utf-8")), 4096)
        self.assertTrue(truncated)
        self.assertEqual(truncated, value[: len(truncated)])

    def test_milvus_index_fallback_can_index_and_search_documents(self) -> None:
        with patch.object(MilvusKnowledgeIndex, "_can_reach_endpoint", return_value=False):
            index = MilvusKnowledgeIndex(
                uri="http://localhost:19530",
                collection_name="emata_test",
                embedding_provider=FakeEmbeddingProvider(),
            )

        index.upsert(
            document_id="doc-finance",
            title="Finance Expense Policy",
            content="Finance reimbursement policy and ERP approval requirements.",
            metadata={
                "organization_id": "org-acme",
                "workspace_id": "workspace-finance",
                "scope": "workspace",
            },
        )
        index.upsert(
            document_id="doc-sales",
            title="Sales Battlecard",
            content="Competitive notes and sales objection handling.",
            metadata={
                "organization_id": "org-acme",
                "workspace_id": "workspace-sales",
                "scope": "workspace",
            },
        )

        results = index.search(
            "approval policy",
            organization_id="org-acme",
            workspace_id="workspace-finance",
            limit=2,
        )

        self.assertEqual(results[0]["document_id"], "doc-finance")
        self.assertNotEqual(results[0]["document_id"], "doc-sales")

    def test_milvus_index_search_raises_when_cancel_event_is_set(self) -> None:
        with patch.object(MilvusKnowledgeIndex, "_can_reach_endpoint", return_value=False):
            index = MilvusKnowledgeIndex(
                uri="http://localhost:19530",
                collection_name="emata_test",
                embedding_provider=FakeEmbeddingProvider(),
            )

        index.upsert(
            document_id="doc-finance",
            title="Finance Expense Policy",
            content="Finance reimbursement policy and ERP approval requirements.",
            metadata={
                "organization_id": "org-acme",
                "workspace_id": "workspace-finance",
                "scope": "workspace",
            },
        )
        cancel_event = threading.Event()
        cancel_event.set()

        with self.assertRaisesRegex(ValueError, "search_canceled"):
            index.search(
                "approval policy",
                organization_id="org-acme",
                workspace_id="workspace-finance",
                limit=2,
                cancel_event=cancel_event,
            )

    def test_milvus_index_skips_sdk_initialization_when_endpoint_unreachable(self) -> None:
        with patch.object(MilvusKnowledgeIndex, "_can_reach_endpoint", return_value=False), patch.object(
            MilvusKnowledgeIndex,
            "_build_sdk_client",
            side_effect=AssertionError("sdk should not initialize"),
        ) as mocked_build:
            index = MilvusKnowledgeIndex(uri="http://localhost:19530", collection_name="emata_test")

        self.assertEqual(index.mode, "fallback")
        self.assertEqual(index.reason, "endpoint_unreachable")
        mocked_build.assert_not_called()

    def test_milvus_index_uses_sdk_after_endpoint_probe_succeeds(self) -> None:
        fake_client = FakeMilvusClient()
        with patch.object(MilvusKnowledgeIndex, "_can_reach_endpoint", return_value=True), patch.object(
            MilvusKnowledgeIndex,
            "_build_sdk_client",
            return_value=fake_client,
        ) as mocked_build:
            index = MilvusKnowledgeIndex(uri="http://localhost:19530", collection_name="emata_test")

        self.assertEqual(index.mode, "sdk")
        self.assertEqual(index.reason, "available")
        self.assertIs(index._client, fake_client)
        mocked_build.assert_called_once()

    def test_milvus_index_sdk_upsert_creates_collection_and_persists_vector_payload(self) -> None:
        fake_client = FakeMilvusClient()
        fake_embedder = FakeEmbeddingProvider()
        with patch.object(MilvusKnowledgeIndex, "_can_reach_endpoint", return_value=True), patch.object(
            MilvusKnowledgeIndex,
            "_build_sdk_client",
            return_value=fake_client,
        ):
            index = MilvusKnowledgeIndex(
                uri="http://localhost:19530",
                collection_name="emata_test",
                embedding_provider=fake_embedder,
            )

        index.upsert(
            document_id="doc-finance",
            title="Finance Expense Policy",
            content="Finance reimbursement policy and ERP approval requirements.",
            metadata={
                "organization_id": "org-acme",
                "workspace_id": "workspace-finance",
                "scope": "workspace",
            },
        )

        self.assertEqual(index.mode, "sdk")
        self.assertEqual(len(fake_client.created), 1)
        self.assertEqual(fake_client.upserts[0]["data"][0]["id"], "doc-finance")
        self.assertEqual(fake_client.upserts[0]["data"][0]["organization_id"], "org-acme")
        self.assertEqual(len(fake_client.upserts[0]["data"][0]["vector"]), 4)
        self.assertEqual(fake_embedder.calls[0], ["Finance Expense Policy\nFinance reimbursement policy and ERP approval requirements."])

    def test_milvus_index_upsert_chunk_preserves_chunk_identifier(self) -> None:
        with patch.object(MilvusKnowledgeIndex, "_can_reach_endpoint", return_value=False):
            index = MilvusKnowledgeIndex(
                uri="http://localhost:19530",
                collection_name="emata_test",
                embedding_provider=FakeEmbeddingProvider(),
            )

        index.upsert_chunk(
            chunk_id="doc-finance-policy-chunk-0",
            title="Finance Expense Policy",
            content="Finance reimbursement policy and ERP approval requirements.",
            metadata={
                "organization_id": "org-acme",
                "workspace_id": "workspace-finance",
                "scope": "workspace",
                "block_type": "legacy_document",
            },
        )

        self.assertIn("doc-finance-policy-chunk-0", index.records)
        self.assertEqual(
            index.records["doc-finance-policy-chunk-0"]["metadata"]["block_type"],
            "legacy_document",
        )

    def test_milvus_index_sdk_search_uses_rewritten_query_and_workspace_filter(self) -> None:
        fake_client = FakeMilvusClient()
        fake_client.collections.add("emata_test")
        fake_client.search_results = [
            [[
                {
                    "id": "doc-finance",
                    "distance": 0.99,
                    "entity": {
                        "id": "doc-finance",
                        "organization_id": "org-acme",
                        "workspace_id": "workspace-finance",
                        "scope": "workspace",
                        "title": "Finance Expense Policy",
                        "content_preview": "Finance reimbursement policy.",
                    },
                }
            ]],
            [[
                {
                    "id": "doc-shared",
                    "distance": 0.95,
                    "entity": {
                        "id": "doc-shared",
                        "organization_id": "org-acme",
                        "workspace_id": "",
                        "scope": "shared",
                        "title": "Company Shared Policy",
                        "content_preview": "Shared approval policy.",
                    },
                }
            ]],
        ]
        fake_embedder = FakeEmbeddingProvider()
        fake_rewriter = FakeQueryRewriter(
            variants=["ERP approval", "ERP approval enterprise resource planning authorize"]
        )
        with patch.object(MilvusKnowledgeIndex, "_can_reach_endpoint", return_value=True), patch.object(
            MilvusKnowledgeIndex,
            "_build_sdk_client",
            return_value=fake_client,
        ):
            index = MilvusKnowledgeIndex(
                uri="http://localhost:19530",
                collection_name="emata_test",
                embedding_provider=fake_embedder,
                query_rewriter=fake_rewriter,
            )

        results = index.search(
            "ERP approval",
            organization_id="org-acme",
            workspace_id="workspace-finance",
            limit=5,
        )

        self.assertEqual([item["document_id"] for item in results], ["doc-finance", "doc-shared"])
        self.assertEqual(len(fake_client.search_calls), 2)
        self.assertIn('organization_id == "org-acme"', fake_client.search_calls[0]["filter"])
        self.assertIn('scope == "shared"', fake_client.search_calls[0]["filter"])
        self.assertIn('workspace_id == "workspace-finance"', fake_client.search_calls[0]["filter"])
        self.assertEqual(fake_rewriter.calls, ["ERP approval"])

    def test_milvus_index_sdk_search_prefers_chunk_zero_over_legacy_document_id(self) -> None:
        fake_client = FakeMilvusClient()
        fake_client.collections.add("emata_test")
        fake_client.search_results = [
            [[
                {
                    "id": "doc-finance",
                    "distance": 0.71,
                    "entity": {
                        "id": "doc-finance",
                        "organization_id": "org-acme",
                        "workspace_id": "workspace-finance",
                        "scope": "workspace",
                        "title": "Finance Expense Policy",
                        "content_preview": "Finance reimbursement policy.",
                    },
                },
                {
                    "id": "doc-finance-chunk-0",
                    "distance": 0.73,
                    "entity": {
                        "id": "doc-finance-chunk-0",
                        "organization_id": "org-acme",
                        "workspace_id": "workspace-finance",
                        "scope": "workspace",
                        "title": "Finance Expense Policy",
                        "content_preview": "Finance reimbursement policy.",
                    },
                },
            ]]
        ]
        with patch.object(MilvusKnowledgeIndex, "_can_reach_endpoint", return_value=True), patch.object(
            MilvusKnowledgeIndex,
            "_build_sdk_client",
            return_value=fake_client,
        ):
            index = MilvusKnowledgeIndex(
                uri="http://localhost:19530",
                collection_name="emata_test",
                embedding_provider=FakeEmbeddingProvider(),
                query_rewriter=FakeQueryRewriter(variants=["finance reimbursement"]),
            )

        results = index.search(
            "finance reimbursement",
            organization_id="org-acme",
            workspace_id="workspace-finance",
            limit=5,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["document_id"], "doc-finance-chunk-0")

    def test_milvus_index_sdk_search_restores_chunk_metadata_from_record_cache(self) -> None:
        fake_client = FakeMilvusClient()
        fake_client.collections.add("emata_test")
        fake_client.search_results = [
            [[
                {
                    "id": "doc-finance-chunk-2",
                    "distance": 0.97,
                    "entity": {
                        "id": "doc-finance-chunk-2",
                        "organization_id": "org-acme",
                        "workspace_id": "workspace-finance",
                        "scope": "workspace",
                        "title": "Finance Expense Policy",
                        "content_preview": "审批摘要",
                    },
                }
            ]]
        ]
        with patch.object(MilvusKnowledgeIndex, "_can_reach_endpoint", return_value=True), patch.object(
            MilvusKnowledgeIndex,
            "_build_sdk_client",
            return_value=fake_client,
        ):
            index = MilvusKnowledgeIndex(
                uri="http://localhost:19530",
                collection_name="emata_test",
                embedding_provider=FakeEmbeddingProvider(),
                query_rewriter=FakeQueryRewriter(variants=["approval"]),
            )

        index.upsert_chunk(
            chunk_id="doc-finance-chunk-2",
            title="Finance Expense Policy",
            content="审批摘要",
            metadata={
                "organization_id": "org-acme",
                "workspace_id": "workspace-finance",
                "scope": "workspace",
                "block_type": "table",
                "section_path": ["财务制度", "审批流程"],
                "page_number": 3,
                "sheet_name": None,
                "slide_number": None,
            },
        )

        results = index.search(
            "approval",
            organization_id="org-acme",
            workspace_id="workspace-finance",
            limit=5,
        )

        self.assertEqual(results[0]["metadata"]["block_type"], "table")
        self.assertEqual(results[0]["metadata"]["section_path"], ["财务制度", "审批流程"])
        self.assertEqual(results[0]["metadata"]["page_number"], 3)

    def test_feishu_mcp_client_builds_npx_delivery_command(self) -> None:
        client = FeishuMcpClient(
            executable="npx",
            package="@larksuiteoapi/lark-mcp",
            transport="stdio",
        )

        command = client.build_command()

        self.assertEqual(command[0], "npx")
        self.assertIn("@larksuiteoapi/lark-mcp", command)
        self.assertIn("--transport", command)

    def test_temporal_runtime_falls_back_when_sdk_missing(self) -> None:
        runtime = TemporalRuntime(target_hostport="temporal:7233", namespace="default")

        description = runtime.describe()

        self.assertEqual(description["workflow_name"], "emata_run_workflow")
        self.assertIn(description["mode"], {"sdk", "fallback"})
        if description["mode"] == "fallback":
            self.assertIn("temporalio", description["reason"])


if __name__ == "__main__":
    unittest.main()
