# Document Ingestion And Upload UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 EMATA 增加真实文件上传、结构化文档解析、中文友好的 chunk 生成与基础上传 UI。

**Architecture:** 解析层引入 `Docling`，中间层新增 `CanonicalBlock` 与 `KnowledgeChunkRecord`，索引层复用现有 `EmbeddingProvider + MilvusKnowledgeIndex`，前端增加上传入口和最小检索调试视图。

**Tech Stack:** Python, FastAPI, Pydantic, PostgreSQL snapshot store, Milvus, Docling, Next.js

---

## 文件结构

- Create: `E:/Project/Agent/backend/app/document_models.py`
- Create: `E:/Project/Agent/backend/app/document_ingestion.py`
- Create: `E:/Project/Agent/backend/tests/test_document_ingestion.py`
- Create: `E:/Project/Agent/backend/tests/test_upload_api.py`
- Modify: `E:/Project/Agent/backend/app/contracts.py`
- Modify: `E:/Project/Agent/backend/app/core.py`
- Modify: `E:/Project/Agent/backend/app/persistence.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/app/integrations.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Modify: `E:/Project/Agent/backend/requirements-optional.txt`
- Create: `E:/Project/Agent/frontend/app/knowledge/page.js`
- Create: `E:/Project/Agent/frontend/components/knowledge-upload-form.js`
- Create: `E:/Project/Agent/frontend/components/knowledge-search-panel.js`
- Create: `E:/Project/Agent/frontend/tests/knowledge-page.test.mjs`
- Modify: `E:/Project/Agent/frontend/lib/api.js`
- Modify: `E:/Project/Agent/frontend/app/page.js`
- Modify: `E:/Project/Agent/README.md`

### Task 1: 先重构搜索返回模型为 chunk 命中对象

**Files:**
- Modify: `E:/Project/Agent/backend/app/contracts.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Test: `E:/Project/Agent/backend/tests/test_api_contract.py`

- [ ] **Step 1: 写失败测试，约束搜索返回 chunk 级字段**

```python
def test_search_response_exposes_chunk_level_metadata(self):
    response = self.client.get("/api/v1/knowledge/search?workspace_id=workspace-finance&query=报销")
    item = response.json()["items"][0]
    self.assertIn("chunk_id", item)
    self.assertIn("block_type", item)
    self.assertIn("section_path", item)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_api_contract.py -v`
Expected: FAIL because response model still assumes document-level result

- [ ] **Step 3: 增加 `ChunkSearchHit` DTO 与响应模型**

```python
class ChunkSearchHit(BaseModel):
    chunk_id: str
    title: str
    snippet: str
    scope: str
    score: float | None = None
    block_type: str | None = None
    section_path: list[str] = []
    page_number: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
```

- [ ] **Step 4: 重写 `search_knowledge()` 返回 DTO，而不是 `KnowledgeDocumentRecord`**

```python
def search_knowledge(self, user: UserRecord, workspace_id: str, query: str):
    results = self.knowledge_index.search(
        query=query,
        organization_id=user.organization_id,
        workspace_id=workspace_id,
        limit=10,
    )
    return [
        ChunkSearchHit(
            chunk_id=item["document_id"],
            title=item["title"],
            snippet=item["content"],
            scope=item["metadata"]["scope"],
            score=item.get("score"),
            block_type=item["metadata"].get("block_type"),
            section_path=item["metadata"].get("section_path", []),
            page_number=item["metadata"].get("page_number"),
            sheet_name=item["metadata"].get("sheet_name"),
            slide_number=item["metadata"].get("slide_number"),
        )
        for item in results
    ]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_api_contract.py -v`
Expected: PASS

### Task 2: 定义上传与 chunk 领域模型

**Files:**
- Create: `E:/Project/Agent/backend/app/document_models.py`
- Modify: `E:/Project/Agent/backend/app/core.py`
- Modify: `E:/Project/Agent/backend/app/persistence.py`
- Test: `E:/Project/Agent/backend/tests/test_document_ingestion.py`

- [ ] **Step 1: 写失败测试，约束 chunk 元数据模型**

```python
from backend.app.document_models import CanonicalBlock, KnowledgeChunkRecord


def test_chunk_record_keeps_position_metadata():
    chunk = KnowledgeChunkRecord(
        id="chunk-1",
        source_file_id="file-1",
        organization_id="org-1",
        workspace_id="workspace-finance",
        scope="workspace",
        title="报销制度",
        content="报销审批正文",
        block_type="paragraph",
        section_path=["第一章", "审批流程"],
        page_number=2,
        sheet_name=None,
        slide_number=None,
        chunk_index=0,
        token_count_estimate=32,
        metadata={"source_type": "pdf"},
    )
    assert chunk.page_number == 2
    assert chunk.section_path == ["第一章", "审批流程"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_document_ingestion.py -v`
Expected: FAIL with import error for `document_models`

- [ ] **Step 3: 写最小实现**

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CanonicalBlock:
    block_type: str
    text: str
    section_path: List[str] = field(default_factory=list)
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeChunkRecord:
    id: str
    source_file_id: str
    organization_id: str
    workspace_id: Optional[str]
    scope: str
    title: str
    content: str
    block_type: str
    section_path: List[str]
    page_number: Optional[int]
    sheet_name: Optional[str]
    slide_number: Optional[int]
    chunk_index: int
    token_count_estimate: int
    metadata: Dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: 在持久化层增加 chunk 保存入口**

```python
def save_chunk(self, chunk: KnowledgeChunkRecord) -> None:
    self._upsert("chunk", chunk.id, _serialize(chunk))
```

- [ ] **Step 5: 运行测试确认通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_document_ingestion.py -v`
Expected: PASS

### Task 3: 引入原始文件持久化与上传状态模型

**Files:**
- Modify: `E:/Project/Agent/backend/app/document_models.py`
- Modify: `E:/Project/Agent/backend/app/persistence.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Test: `E:/Project/Agent/backend/tests/test_upload_api.py`

- [ ] **Step 1: 写失败测试，约束上传状态查询接口**

```python
def test_get_upload_status_returns_storage_metadata(self):
    response = self.client.get("/api/v1/knowledge/uploads/upload-1")
    self.assertEqual(response.status_code, 200)
    payload = response.json()
    self.assertIn("storage_path", payload)
    self.assertIn("status", payload)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_upload_api.py -v`
Expected: FAIL with 404

- [ ] **Step 3: 增加 `KnowledgeSourceFile` 与 `save_source_file()`**

```python
@dataclass
class KnowledgeSourceFile:
    id: str
    organization_id: str
    workspace_id: Optional[str]
    scope: str
    filename: str
    mime_type: str
    source_type: str
    storage_path: str
    status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
```

- [ ] **Step 4: 规定存储策略**

```python
class StorageAdapter(Protocol):
    def put_bytes(self, path: str, payload: bytes, content_type: str) -> str:
        pass

    def get_to_local_path(self, path: str) -> str:
        pass

    def delete(self, path: str) -> None:
        pass
```

- [ ] **Step 5: 增加 `GET /api/v1/knowledge/uploads/{id}` 路由与测试通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_upload_api.py -v`
Expected: PASS

### Task 4: 抽出统一 StorageAdapter，避免本地和 MinIO 语义分裂

**Files:**
- Create: `E:/Project/Agent/backend/app/storage.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/app/document_ingestion.py`
- Test: `E:/Project/Agent/backend/tests/test_upload_api.py`

- [ ] **Step 1: 写失败测试，约束 MinIO 和本地实现返回真实 storage_path**

```python
def test_storage_adapter_returns_real_storage_path():
    adapter = FilesystemStorageAdapter(base_dir="E:/Project/Agent/tmp/uploads")
    path = adapter.put_bytes("org-1/workspace-finance/file-1/policy.txt", b"abc", "text/plain")
    assert path.endswith("org-1/workspace-finance/file-1/policy.txt")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_upload_api.py -v`
Expected: FAIL because `FilesystemStorageAdapter` does not exist

- [ ] **Step 3: 定义接口与本地实现**

```python
class FilesystemStorageAdapter:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def put_bytes(self, path: str, payload: bytes, content_type: str) -> str:
        target = self.base_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return str(target)
```

- [ ] **Step 4: 定义 MinIO 实现并在容器中按配置切换**

```python
class MinioStorageAdapter:
    def put_bytes(self, path: str, payload: bytes, content_type: str) -> str:
        self.client.put_object(self.bucket_name, path, io.BytesIO(payload), len(payload), content_type=content_type)
        return f"{self.bucket_name}/{path}"
```

- [ ] **Step 5: 运行测试确认通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_upload_api.py -v`
Expected: PASS

### Task 5: 引入 Docling 解析适配层

**Files:**
- Create: `E:/Project/Agent/backend/app/document_ingestion.py`
- Modify: `E:/Project/Agent/backend/requirements-optional.txt`
- Test: `E:/Project/Agent/backend/tests/test_document_ingestion.py`

- [ ] **Step 1: 写失败测试，约束解析适配器输出 CanonicalBlock**

```python
from backend.app.document_ingestion import DoclingParserAdapter


def test_docling_adapter_returns_canonical_blocks():
    adapter = DoclingParserAdapter()
    blocks = adapter._normalize_mock_blocks(
        [
            {"type": "heading", "text": "第一章 总则", "page_number": 1},
            {"type": "paragraph", "text": "这里是正文", "page_number": 1},
        ]
    )
    assert blocks[0].block_type == "heading"
    assert blocks[1].text == "这里是正文"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_document_ingestion.py -v`
Expected: FAIL because `DoclingParserAdapter` does not exist

- [ ] **Step 3: 增加依赖并实现适配骨架**

```python
class DoclingParserAdapter:
    def parse_file(self, file_path: str, source_type: str) -> list[CanonicalBlock]:
        if source_type == "text/plain":
            with open(file_path, "r", encoding="utf-8") as handle:
                return [CanonicalBlock(block_type="paragraph", text=handle.read().strip())]
        return []

    def _normalize_mock_blocks(self, raw_blocks):
        return [
            CanonicalBlock(
                block_type=item["type"],
                text=item["text"],
                page_number=item.get("page_number"),
            )
            for item in raw_blocks
        ]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_document_ingestion.py -v`
Expected: PASS

### Task 6: 实现结构感知 chunk 策略

**Files:**
- Modify: `E:/Project/Agent/backend/app/document_ingestion.py`
- Test: `E:/Project/Agent/backend/tests/test_document_ingestion.py`

- [ ] **Step 1: 写失败测试，覆盖中文段落与标题边界**

```python
from backend.app.document_ingestion import ChunkPolicyEngine
from backend.app.document_models import CanonicalBlock


def test_chunker_splits_by_heading_before_size_limit():
    engine = ChunkPolicyEngine(soft_limit_chars=20, hard_limit_chars=40)
    blocks = [
        CanonicalBlock(block_type="heading", text="第一章"),
        CanonicalBlock(block_type="paragraph", text="报销制度第一段。"),
        CanonicalBlock(block_type="heading", text="第二章"),
        CanonicalBlock(block_type="paragraph", text="审批流程第二段。"),
    ]
    chunks = engine.build_chunks(blocks, source_file_id="file-1", title="制度")
    assert len(chunks) == 2
    assert chunks[0].title == "制度"


def test_chunker_keeps_table_as_separate_chunk():
    engine = ChunkPolicyEngine(soft_limit_chars=200, hard_limit_chars=300)
    blocks = [
        CanonicalBlock(block_type="paragraph", text="报销制度说明"),
        CanonicalBlock(block_type="table", text="项目 | 金额\\n交通 | 100"),
    ]
    chunks = engine.build_chunks(blocks, source_file_id="file-2", title="表格测试")
    assert len(chunks) == 2
    assert chunks[1].block_type == "table"


def test_chunker_does_not_merge_across_slides():
    engine = ChunkPolicyEngine()
    blocks = [
        CanonicalBlock(block_type="slide", text="第一页内容", slide_number=1),
        CanonicalBlock(block_type="slide", text="第二页内容", slide_number=2),
    ]
    chunks = engine.build_chunks(blocks, source_file_id="file-3", title="销售PPT")
    assert chunks[0].slide_number == 1
    assert chunks[1].slide_number == 2


def test_chunker_keeps_sheet_name_in_metadata():
    engine = ChunkPolicyEngine()
    blocks = [CanonicalBlock(block_type="sheet", text="报销记录", sheet_name="Sheet1")]
    chunks = engine.build_chunks(blocks, source_file_id="file-4", title="财务表")
    assert chunks[0].sheet_name == "Sheet1"


def test_chunker_splits_overlong_chinese_paragraph_by_token_budget():
    engine = ChunkPolicyEngine(soft_limit_chars=900, hard_limit_chars=1400, soft_limit_tokens=100, hard_limit_tokens=160)
    blocks = [CanonicalBlock(block_type="paragraph", text="报销制度说明。" * 200)]
    chunks = engine.build_chunks(blocks, source_file_id="file-5", title="长段落")
    assert len(chunks) > 1
    assert all(chunk.token_count_estimate <= 160 for chunk in chunks)


def test_chunker_splits_wide_table_with_header_repeated():
    engine = ChunkPolicyEngine(soft_limit_chars=300, hard_limit_chars=500, soft_limit_tokens=80, hard_limit_tokens=120)
    blocks = [CanonicalBlock(block_type="table", text="项目|金额|部门\\n" + "\\n".join([f"行{i}|100|财务" for i in range(50)]))]
    chunks = engine.build_chunks(blocks, source_file_id="file-6", title="宽表")
    assert len(chunks) > 1
    assert all("项目|金额|部门" in chunk.content for chunk in chunks)


def test_chunker_splits_long_slide_notes_without_crossing_slides():
    engine = ChunkPolicyEngine(soft_limit_chars=300, hard_limit_chars=500, soft_limit_tokens=80, hard_limit_tokens=120)
    blocks = [CanonicalBlock(block_type="slide", text="备注。" * 120, slide_number=3)]
    chunks = engine.build_chunks(blocks, source_file_id="file-7", title="备注页")
    assert len(chunks) > 1
    assert all(chunk.slide_number == 3 for chunk in chunks)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_document_ingestion.py -v`
Expected: FAIL because `ChunkPolicyEngine` does not exist

- [ ] **Step 3: 写最小实现，覆盖双预算、标题边界、slide/sheet 隔离和二级切分**

```python
class ChunkPolicyEngine:
    def __init__(
        self,
        soft_limit_chars=900,
        hard_limit_chars=1400,
        soft_limit_tokens=600,
        hard_limit_tokens=900,
        min_merge_chars=220,
    ):
        self.soft_limit_chars = soft_limit_chars
        self.hard_limit_chars = hard_limit_chars
        self.soft_limit_tokens = soft_limit_tokens
        self.hard_limit_tokens = hard_limit_tokens
        self.min_merge_chars = min_merge_chars

    def build_chunks(self, blocks, source_file_id, title):
        chunks = []
        current = []
        last_slide = None
        last_sheet = None
        for block in blocks:
            boundary = (
                block.block_type in {"heading", "table"}
                or (block.slide_number is not None and block.slide_number != last_slide)
                or (block.sheet_name is not None and block.sheet_name != last_sheet)
            )
            if boundary and current:
                chunks.append(self._flush(current, source_file_id, title, len(chunks)))
                current = []
            current.append(block)
            last_slide = block.slide_number if block.slide_number is not None else last_slide
            last_sheet = block.sheet_name if block.sheet_name is not None else last_sheet
        if current:
            chunks.append(self._flush(current, source_file_id, title, len(chunks)))
        return chunks

    def _needs_secondary_split(self, text: str, token_count: int) -> bool:
        return len(text) > self.hard_limit_chars or token_count > self.hard_limit_tokens
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_document_ingestion.py -v`
Expected: PASS

### Task 7: 兼容旧文档，把 seed/旧记录回填成单 chunk

**Files:**
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/app/persistence.py`
- Test: `E:/Project/Agent/backend/tests/test_persistence.py`
- Test: `E:/Project/Agent/backend/tests/test_api_contract.py`

- [ ] **Step 1: 写失败测试，约束旧文档可被 chunk 搜索命中**

```python
def test_seed_document_is_backfilled_as_single_chunk(self):
    container = build_test_container()
    items = container.search_knowledge(container.store.users["user-analyst"], "workspace-finance", "expense policy")
    assert any(item.chunk_id for item in items)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_persistence.py E:/Project/Agent/backend/tests/test_api_contract.py -v`
Expected: FAIL because old documents are not backfilled into chunk records

- [ ] **Step 3: 在容器初始化时回填旧文档**

```python
def _hydrate_legacy_documents_as_chunks(self) -> None:
    for document in self.store.documents.values():
        chunk = KnowledgeChunkRecord(
            id=f"{document.id}-chunk-0",
            source_file_id=document.id,
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
            scope=document.scope,
            title=document.title,
            content=document.content,
            block_type="legacy_document",
            section_path=[],
            page_number=None,
            sheet_name=None,
            slide_number=None,
            chunk_index=0,
            token_count_estimate=len(document.content) // 2,
            metadata={"legacy": True},
        )
        self.store.save_chunk(chunk)
        self.knowledge_index.upsert_chunk(
            chunk.id,
            chunk.title,
            chunk.content,
            {
                "organization_id": chunk.organization_id,
                "workspace_id": chunk.workspace_id,
                "scope": chunk.scope,
                "block_type": chunk.block_type,
                "section_path": chunk.section_path,
                "page_number": chunk.page_number,
                "sheet_name": chunk.sheet_name,
                "slide_number": chunk.slide_number,
            },
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_persistence.py E:/Project/Agent/backend/tests/test_api_contract.py -v`
Expected: PASS

### Task 8: 扩展上传 API 与服务编排

**Files:**
- Modify: `E:/Project/Agent/backend/app/contracts.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Test: `E:/Project/Agent/backend/tests/test_upload_api.py`

- [ ] **Step 1: 写失败测试，覆盖 multipart 上传**

```python
def test_upload_endpoint_accepts_multipart_file(self):
    response = self.client.post(
        "/api/v1/knowledge/uploads",
        files={"file": ("policy.txt", b"报销制度正文", "text/plain")},
        data={"workspace_id": "workspace-finance", "scope": "workspace"},
    )
    self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_upload_api.py -v`
Expected: FAIL with 404

- [ ] **Step 3: 增加上传路由**

```python
@public_router.post("/knowledge/uploads")
async def upload_knowledge_file(
    workspace_id: str = Form(...),
    scope: str = Form("workspace"),
    file: UploadFile = File(...),
    user: UserRecord = Depends(get_current_user),
    container: ServiceContainer = Depends(get_service_container),
):
    payload = await file.read()
    return container.ingest_uploaded_file(
        user=user,
        workspace_id=workspace_id,
        scope=scope,
        filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
        file_bytes=payload,
    )
```

- [ ] **Step 4: 在服务层增加上传编排**

```python
def ingest_uploaded_file(self, user, workspace_id, scope, filename, content_type, file_bytes):
    self.assert_workspace_access(user, workspace_id)
    return self.document_ingestion_service.ingest_bytes(
        organization_id=user.organization_id,
        workspace_id=workspace_id,
        scope=scope,
        filename=filename,
        content_type=content_type,
        file_bytes=file_bytes,
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_upload_api.py -v`
Expected: PASS

### Task 9: 把 chunk 写入 PostgreSQL 与 Milvus

**Files:**
- Modify: `E:/Project/Agent/backend/app/persistence.py`
- Modify: `E:/Project/Agent/backend/app/integrations.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Test: `E:/Project/Agent/backend/tests/test_integrations.py`
- Test: `E:/Project/Agent/backend/tests/test_persistence.py`

- [ ] **Step 1: 写失败测试，约束 Milvus upsert 以 chunk 为粒度**

```python
def test_milvus_upsert_uses_chunk_metadata(self):
    index = MilvusKnowledgeIndex("http://milvus", "chunks", embedding_provider=FakeEmbeddingProvider())
    index.upsert_chunk(
        chunk_id="chunk-1",
        title="报销制度",
        content="审批正文",
        metadata={
            "page_number": 2,
            "scope": "workspace",
            "workspace_id": "workspace-finance",
            "organization_id": "org-1",
        },
    )
    entity = index.records["chunk-1"]
    assert entity["metadata"]["page_number"] == 2
    assert entity["metadata"]["workspace_id"] == "workspace-finance"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_integrations.py -v`
Expected: FAIL because `upsert_chunk` does not exist

- [ ] **Step 3: 实现 chunk upsert**

```python
def upsert_chunk(self, chunk_id, title, content, metadata):
    vector = self.embedding_provider.embed_texts([f"{title}\n{content}"])[0]
    self.records[chunk_id] = {
        "document_id": chunk_id,
        "title": title,
        "content": content,
        "metadata": metadata,
    }
    if self.mode == "sdk" and self._client:
        self._ensure_collection(len(vector))
        self._client.upsert(
            self.collection_name,
            [{
                "id": chunk_id,
                "organization_id": metadata["organization_id"],
                "workspace_id": metadata.get("workspace_id") or "",
                "scope": metadata["scope"],
                "title": title,
                "content_preview": content[:4096],
                "vector": vector,
            }],
        )
```

- [ ] **Step 4: 持久化层增加 chunk 保存与恢复**

```python
def save_chunk(self, chunk: KnowledgeChunkRecord) -> None:
    self._upsert("chunk", chunk.id, _serialize(chunk))

persisted_chunks = {
    key: self._build_chunk(value)
    for key, value in grouped.get("chunk", {}).items()
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_integrations.py E:/Project/Agent/backend/tests/test_persistence.py -v`
Expected: PASS

### Task 10: 暴露检索 trace 与 chunk 元数据

**Files:**
- Modify: `E:/Project/Agent/backend/app/contracts.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Test: `E:/Project/Agent/backend/tests/test_api_contract.py`

- [ ] **Step 1: 写失败测试，约束搜索返回 page/section/block_type**

```python
def test_search_response_exposes_chunk_metadata(self):
    response = self.client.get("/api/v1/knowledge/search?workspace_id=workspace-finance&query=报销")
    item = response.json()["items"][0]
    self.assertIn("block_type", item)
    self.assertIn("section_path", item)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_api_contract.py -v`
Expected: FAIL because response model lacks fields

- [ ] **Step 3: 扩展响应模型**

```python
class KnowledgeSearchItemResponse(BaseModel):
    title: str
    snippet: str
    scope: str
    score: float | None = None
    block_type: str | None = None
    section_path: list[str] = []
    page_number: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_api_contract.py -v`
Expected: PASS

### Task 11: 增加最小上传 UI 与检索调试页

**Files:**
- Create: `E:/Project/Agent/frontend/app/knowledge/page.js`
- Create: `E:/Project/Agent/frontend/components/knowledge-upload-form.js`
- Create: `E:/Project/Agent/frontend/components/knowledge-search-panel.js`
- Modify: `E:/Project/Agent/frontend/lib/api.js`
- Modify: `E:/Project/Agent/frontend/app/page.js`
- Test: `E:/Project/Agent/frontend/tests/knowledge-page.test.mjs`

- [ ] **Step 1: 写失败测试，约束上传页包含表单与结果区**

```javascript
test("knowledge page renders upload and search panels", async () => {
  const html = await renderKnowledgePage();
  assert.match(html, /Upload Knowledge/i);
  assert.match(html, /Search Knowledge/i);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `node --test E:/Project/Agent/frontend/tests/knowledge-page.test.mjs`
Expected: FAIL because page does not exist

- [ ] **Step 3: 实现最小 UI**

```javascript
export default function KnowledgePage() {
  return (
    <main>
      <KnowledgeUploadForm />
      <KnowledgeSearchPanel />
    </main>
  );
}
```

- [ ] **Step 4: 连接前端 API**

```javascript
export async function uploadKnowledgeFile(formData) {
  return fetch(`${API_BASE_URL}/api/v1/knowledge/uploads`, {
    method: "POST",
    body: formData,
  });
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `node --test E:/Project/Agent/frontend/tests/knowledge-page.test.mjs`
Expected: PASS

### Task 12: 真实样本端到端回归与说明文档

**Files:**
- Modify: `E:/Project/Agent/README.md`
- Test: `E:/Project/Agent/backend/tests/test_document_ingestion.py`
- Test: `E:/Project/Agent/backend/tests/test_upload_api.py`

- [ ] **Step 1: 增加样本文档验证用例**

```python
def test_xlsx_chunk_keeps_sheet_boundary():
    adapter = ChunkPolicyEngine()
    blocks = [
        CanonicalBlock(block_type="sheet", text="一月数据", sheet_name="January"),
        CanonicalBlock(block_type="sheet", text="二月数据", sheet_name="February"),
    ]
    chunks = adapter.build_chunks(blocks, source_file_id="xlsx-1", title="月度报表")
    assert chunks[0].sheet_name == "January"
    assert chunks[1].sheet_name == "February"


def test_pptx_chunk_keeps_slide_boundary():
    adapter = ChunkPolicyEngine()
    blocks = [
        CanonicalBlock(block_type="slide", text="销售策略", slide_number=1),
        CanonicalBlock(block_type="slide", text="价格策略", slide_number=2),
    ]
    chunks = adapter.build_chunks(blocks, source_file_id="pptx-1", title="销售资料")
    assert len(chunks) == 2
    assert chunks[1].slide_number == 2
```

- [ ] **Step 2: 运行后端关键测试**

Run: `conda run -n emata python -m unittest E:/Project/Agent/backend/tests/test_document_ingestion.py E:/Project/Agent/backend/tests/test_upload_api.py E:/Project/Agent/backend/tests/test_integrations.py -v`
Expected: PASS

- [ ] **Step 3: 增加端到端样本测试**

```python
def test_docx_upload_to_search_end_to_end(self):
    upload = self.client.post(
        "/api/v1/knowledge/uploads",
        files={"file": ("policy.docx", open("E:/Project/Agent/tmp/samples/policy.docx", "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"workspace_id": "workspace-finance", "scope": "workspace"},
    ).json()
    search = self.client.get("/api/v1/knowledge/search?workspace_id=workspace-finance&query=报销审批").json()
    assert any(item["chunk_id"] for item in search["items"])
    assert any(item["section_path"] for item in search["items"])


def test_pptx_upload_to_search_end_to_end(self):
    upload = self.client.post(
        "/api/v1/knowledge/uploads",
        files={"file": ("battlecard.pptx", open("E:/Project/Agent/tmp/samples/battlecard.pptx", "rb"), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        data={"workspace_id": "workspace-sales", "scope": "workspace"},
    ).json()
    search = self.client.get("/api/v1/knowledge/search?workspace_id=workspace-sales&query=价格策略").json()
    assert any(item["slide_number"] == 2 for item in search["items"])
```

- [ ] **Step 4: 运行前端测试**

Run: `node --test E:/Project/Agent/frontend/tests/knowledge-page.test.mjs E:/Project/Agent/frontend/tests/dashboard.test.mjs`
Expected: PASS

- [ ] **Step 5: 更新 README**

```markdown
## Knowledge Upload

- Supported formats: PDF, DOCX, PPTX, XLSX
- Parser: Docling
- Chunk strategy: structure-aware, Chinese-friendly
- Search metadata: section path, page/sheet/slide, block type
```

- [ ] **Step 6: 汇总验证命令**

Run: `docker compose up -d --build`
Expected: API, console, milvus, temporal worker all healthy
