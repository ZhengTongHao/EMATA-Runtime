import os
import json
import sqlite3
import tempfile
import unittest

from app.document_models import KnowledgeChunkRecord, KnowledgeSourceFile, UploadStatus
from app.integrations import TemporalRuntime
from app.services import ServiceContainer


class TestFallbackTemporalRuntime(TemporalRuntime):
    def __init__(self) -> None:
        super().__init__(target_hostport="temporal:7233", namespace="default")
        self.mode = "fallback"
        self.reason = "test_runtime"


class PersistenceTestCase(unittest.TestCase):
    def test_store_repairs_legacy_finance_seed_documents_and_corrupted_demo_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            database_path = os.path.join(tempdir, "emata.db")
            database_url = f"sqlite:///{database_path}"
            connection = sqlite3.connect(database_path)
            connection.execute(
                """
                CREATE TABLE state_snapshots (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_id)
                )
                """
            )
            legacy_finance_document = {
                "id": "doc-finance-policy",
                "organization_id": "org-acme",
                "workspace_id": "workspace-finance",
                "scope": "workspace",
                "title": "Finance Expense Policy",
                "content": "Finance policy for reimbursements, ERP changes, and approval policy steps.",
                "source_type": "manual",
            }
            corrupted_reference_document = {
                "id": "doc-cf31dedc",
                "organization_id": "org-acme",
                "workspace_id": "workspace-finance",
                "scope": "shared",
                "title": "Expense Approval Quick Reference",
                "content": "???????3000?????????3000????????????3000??????????????10000?????????????????????800??",
                "source_type": "manual",
            }
            corrupted_reference_chunk = {
                "id": "doc-cf31dedc-chunk-0",
                "source_file_id": "doc-cf31dedc",
                "organization_id": "org-acme",
                "workspace_id": "workspace-finance",
                "scope": "shared",
                "title": "Expense Approval Quick Reference",
                "content": "???????3000?????????3000????????????3000??????????????10000?????????????????????800??",
                "block_type": "legacy_document",
                "section_path": [],
                "page_number": None,
                "sheet_name": None,
                "slide_number": None,
                "chunk_index": 0,
                "token_count_estimate": 40,
                "metadata": {"legacy": True, "source_type": "manual"},
            }
            for entity_type, entity_id, payload in [
                ("document", "doc-finance-policy", legacy_finance_document),
                ("document", "doc-cf31dedc", corrupted_reference_document),
                ("chunk", "doc-cf31dedc-chunk-0", corrupted_reference_chunk),
            ]:
                connection.execute(
                    "INSERT INTO state_snapshots(entity_type, entity_id, payload) VALUES (?, ?, ?)",
                    (entity_type, entity_id, json.dumps(payload, ensure_ascii=False)),
                )
            connection.commit()
            connection.close()

            container = ServiceContainer(
                database_url=database_url,
                temporal_runtime=TestFallbackTemporalRuntime(),
            )

            self.assertIn("doc-finance-policy", container.store.documents)
            self.assertIn("doc-finance-quick-reference", container.store.documents)
            self.assertNotIn("doc-cf31dedc", container.store.documents)
            self.assertTrue(
                container.store.documents["doc-finance-policy"].content.endswith(
                    "Amounts above 3000 CNY require additional finance manager approval."
                )
            )
            self.assertIn(
                "Claims above 10000 CNY require finance director approval.",
                container.store.documents["doc-finance-quick-reference"].content,
            )
            self.assertNotIn("doc-cf31dedc-chunk-0", container.store.chunks)
            self.assertIn("doc-finance-quick-reference-chunk-0", container.store.chunks)
            container.close()

    def test_seed_document_is_backfilled_as_single_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            database_url = f"sqlite:///{os.path.join(tempdir, 'emata.db')}"

            container = ServiceContainer(
                database_url=database_url,
                temporal_runtime=TestFallbackTemporalRuntime(),
            )

            self.assertIn("doc-finance-policy-chunk-0", container.store.chunks)
            user = container.get_current_user()
            payload = container.search_knowledge(user, "workspace-finance", "expense policy")
            items = payload["items"]

            self.assertTrue(any(item["chunk_id"] == "doc-finance-policy-chunk-0" for item in items))
            container.close()

    def test_sqlalchemy_store_persists_runs_and_memory_across_container_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            database_url = f"sqlite:///{os.path.join(tempdir, 'emata.db')}"

            first = ServiceContainer(
                database_url=database_url,
                temporal_runtime=TestFallbackTemporalRuntime(),
            )
            user = first.get_current_user()
            run = first.create_run(
                user=user,
                workspace_id="workspace-finance",
                title="Persistent run",
                goal="Verify SQL-backed persistence.",
                requested_capability="report.generate",
            )
            first.append_memory_turn(
                user=user,
                run_id=run.id,
                role="user",
                content="请记住输出语言为中文。",
                facts=[{"key": "language", "value": "zh-CN"}],
            )
            first.close()

            second = ServiceContainer(
                database_url=database_url,
                temporal_runtime=TestFallbackTemporalRuntime(),
            )
            persisted_run = second.get_run(user, run.id)
            persisted_memory = second.get_memory_snapshot(user, run.id)

            self.assertEqual(persisted_run.title, "Persistent run")
            self.assertEqual(persisted_memory["total_turns"], 1)
            self.assertEqual(persisted_memory["facts"][0].value, "zh-CN")
            second.close()

    def test_sqlalchemy_store_persists_chunks_across_container_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            database_url = f"sqlite:///{os.path.join(tempdir, 'emata.db')}"

            first = ServiceContainer(
                database_url=database_url,
                temporal_runtime=TestFallbackTemporalRuntime(),
            )
            chunk = KnowledgeChunkRecord(
                id="chunk-finance-1",
                source_file_id="file-finance-1",
                organization_id="org-acme",
                workspace_id="workspace-finance",
                scope="workspace",
                title="报销制度",
                content="审批正文",
                block_type="paragraph",
                section_path=["第一章"],
                page_number=1,
                sheet_name=None,
                slide_number=None,
                chunk_index=0,
                token_count_estimate=16,
                metadata={"source_type": "pdf"},
            )
            first.store.chunks[chunk.id] = chunk
            first.store.save_chunk(chunk)
            first.close()

            second = ServiceContainer(
                database_url=database_url,
                temporal_runtime=TestFallbackTemporalRuntime(),
            )

            self.assertIn(chunk.id, second.store.chunks)
            self.assertEqual(second.store.chunks[chunk.id].section_path, ["第一章"])
            second.close()

    def test_sqlalchemy_store_persists_source_files_across_container_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            database_url = f"sqlite:///{os.path.join(tempdir, 'emata.db')}"

            first = ServiceContainer(
                database_url=database_url,
                temporal_runtime=TestFallbackTemporalRuntime(),
            )
            source_file = KnowledgeSourceFile(
                id="upload-1",
                organization_id="org-acme",
                workspace_id="workspace-finance",
                scope="workspace",
                filename="policy.docx",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                source_type="docx",
                storage_path="knowledge-source-files/org-acme/workspace-finance/upload-1/policy.docx",
                status=UploadStatus.PENDING,
            )
            first.store.source_files[source_file.id] = source_file
            first.store.save_source_file(source_file)
            first.close()

            second = ServiceContainer(
                database_url=database_url,
                temporal_runtime=TestFallbackTemporalRuntime(),
            )

            self.assertIn(source_file.id, second.store.source_files)
            self.assertEqual(
                second.store.source_files[source_file.id].storage_path,
                source_file.storage_path,
            )
            self.assertEqual(
                second.store.source_files[source_file.id].status,
                UploadStatus.PENDING,
            )
            second.close()


if __name__ == "__main__":
    unittest.main()
