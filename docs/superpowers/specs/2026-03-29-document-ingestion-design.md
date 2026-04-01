# 文档上传与结构化 Chunk 设计稿

## 目标

为 EMATA 增加一条可落地的企业知识文档上传链路，覆盖 `PDF / DOCX / PPTX / XLSX` 四类首批格式，并解决当前实现中的三个核心问题：

1. 当前 `/api/v1/knowledge/documents` 只接受 `title + content`，没有真实文件上传与解析。
2. 当前入库粒度是整篇文本，缺乏可控 chunk，检索质量会随文档长度快速下降。
3. 中文、表格、PPT 分页、Excel 表块等结构信息没有被保留，后续检索和引用质量不稳定。

目标不是一步到位做成全功能文档平台，而是在当前 `FastAPI + PostgreSQL + Milvus + Qwen embedding` 基础上，引入一条结构正确、可验证、可扩展的 ingestion pipeline。

## 非目标

- 本期不做批量目录导入。
- 本期不做复杂权限工作流，只沿用现有 `workspace/shared` 作用域。
- 本期不做在线文档预览器。
- 本期不做通用 OCR 控制台配置面板。
- 本期不替换现有 `Milvus + EmbeddingProvider` 检索底座。

## 当前现状与问题

当前代码的关键现状如下：

- [contracts.py](/E:/Project/Agent/backend/app/contracts.py) 的 `KnowledgeDocumentCreateRequest` 只包含 `workspace_id / scope / title / content`。
- [services.py](/E:/Project/Agent/backend/app/services.py) 的 `ingest_knowledge()` 直接把整段文本写入 `KnowledgeDocumentRecord`，随后整段向量化。
- [integrations.py](/E:/Project/Agent/backend/app/integrations.py) 的 `MilvusKnowledgeIndex.upsert()` 当前以单条记录为粒度写入 Milvus，没有 chunk 元数据。

这条链路对短文本还能工作，但一旦进入真实办公文档，会出现这些确定性问题：

- 长文档 embedding 输入过大，语义被平均化。
- 标题、正文、表格被混为一体，检索命中不稳定。
- 中文段落和英文句界规则不同，固定长度切分容易切坏句意。
- PPT/XLSX 的最佳切分边界与 PDF/DOCX 明显不同，不能共用简单规则。

## 选型结论

### 推荐方案

采用 `Docling + 自定义 structure-aware chunker + 现有 Milvus/Qwen 检索层`。

原因：

- `Docling` 对混合办公文档更适合当前需求，支持 `PDF / DOCX / XLSX / PPTX / HTML / Markdown / 图片`，并输出统一结构化文档对象。
- 解析层与 chunk 层分离后，可以把“能读文件”和“切得好”两个问题拆开处理。
- 保留现有 `EmbeddingProvider`、`MilvusKnowledgeIndex`、`ServiceContainer`，避免推翻已经跑通的底座。

### 备选方案

1. `Unstructured` 一体化解析与 chunk
- 优点：接入快，现成 element/chunking 成熟。
- 缺点：对于 PDF 复杂版面、后续结构化引用和表格处理，灵活性不如 `Docling + 自定义 chunker`。

2. `Docling + 通用 splitter`
- 优点：实现简单。
- 缺点：仍会丢失一部分结构信息，不能真正解决“标题/表格/分页切坏”的核心问题。

结论：本期采用 `Docling` 作为解析器，chunk 策略自行控制。

## 架构设计

### 总体链路

```text
前端上传文件
-> FastAPI Upload API
-> DocumentIngestionService
-> DoclingParserAdapter
-> CanonicalBlockNormalizer
-> ChunkPolicyEngine
-> ChunkRecord 持久化到 PostgreSQL
-> EmbeddingProvider
-> Milvus chunk upsert
-> 返回上传结果与解析摘要
```

### 组件边界

1. `DocumentIngestionService`
- 负责上传入口、文件类型识别、调用解析器、落库、索引、错误聚合。
- 对上提供统一接口，对下编排 parser / normalizer / chunker / indexer。

2. `DoclingParserAdapter`
- 负责把真实文件解析为统一的中间结构。
- 输出不直接面向 Milvus，而是面向平台自己的 `CanonicalBlock` 模型。

3. `CanonicalBlockNormalizer`
- 清理解析结果中的噪声与不稳定字段。
- 负责统一块类型：`heading / paragraph / list / table / sheet / slide / caption / footer`。

4. `ChunkPolicyEngine`
- 根据文档类型和块类型生成 `ChunkRecord`。
- 负责中文友好、表格隔离、分页策略、大小阈值控制。

5. `KnowledgeIndexer`
- 负责把 chunk 送入现有 embedding 与 Milvus。
- 保证 PostgreSQL 是文档真相源，Milvus 是检索索引。

6. `KnowledgeSearchAssembler`
- 负责把 Milvus 返回的 `chunk_id` 组装成对外可返回的搜索命中对象。
- 统一输出 `ChunkSearchHit`，而不是直接复用旧的 `KnowledgeDocumentRecord`。

7. `StorageAdapter`
- 负责原始文件 `put / get / delete / exists`。
- 提供两种实现：
  - `MinioStorageAdapter`
  - `FilesystemStorageAdapter`
- 上层服务不直接拼路径，不直接操作本地文件系统。

## 数据模型

### 新增实体

1. `KnowledgeSourceFile`
- 表示一次上传的原始文件
- 字段建议：
  - `id`
  - `organization_id`
  - `workspace_id`
  - `scope`
  - `filename`
  - `mime_type`
  - `source_type`
  - `storage_path`
  - `status`
  - `error_code`
  - `error_message`
  - `created_at`

2. `KnowledgeChunkRecord`
- 表示一个检索粒度 chunk
- 字段建议：
  - `id`
  - `source_file_id`
  - `organization_id`
  - `workspace_id`
  - `scope`
  - `title`
  - `content`
  - `block_type`
  - `section_path`
  - `page_number`
  - `sheet_name`
  - `slide_number`
  - `chunk_index`
  - `token_count_estimate`
  - `metadata_json`

3. `ChunkSearchHit`
- 表示对外检索返回对象
- 字段建议：
  - `chunk_id`
  - `source_file_id`
  - `title`
  - `snippet`
  - `scope`
  - `score`
  - `block_type`
  - `section_path`
  - `page_number`
  - `sheet_name`
  - `slide_number`
  - `workspace_id`

### 兼容策略

- 现有 `KnowledgeDocumentRecord` 暂时保留，作为兼容旧接口与种子数据的轻量模型。
- 新上传链路写入 `KnowledgeSourceFile + KnowledgeChunkRecord`。
- 检索层优先使用 chunk 记录；对外接口由 `ChunkSearchHit` 承载返回，不再假设 Milvus 返回的是文档级 ID。
- 旧文档继续保留兼容查询，后续再迁移。

## 原始文件存储策略

### 真相源

- 原始上传文件进入对象存储，优先使用现有 `MinIO/S3`。
- 桶建议为 `knowledge-source-files`。
- `KnowledgeSourceFile.storage_path` 保存真实对象键，例如 `knowledge-source-files/org-1/workspace-finance/file-1/original.docx`。
- 本地 fallback 仍通过 `FilesystemStorageAdapter` 返回真实文件路径，例如 `tmp/uploads/org-1/workspace-finance/file-1/original.docx`。

### 解析临时文件

- `Docling` 解析时从对象存储取回文件，写入服务本地临时目录。
- `Docling` 解析时统一通过 `StorageAdapter.get()` 取文件。
- 临时文件只用于解析，完成后立即删除。
- 本地开发若未启用 MinIO，允许使用 `FilesystemStorageAdapter`，但接口保持一致。

### 清理策略

- 上传成功后保留原始文件，支持问题排查和重新切分。
- 上传失败且对象文件已落地时，保留文件但状态标为 `failed`，便于排查。
- 临时解析目录在单次任务结束后清理。

## Chunk 策略

### 核心原则

1. 结构边界优先于长度边界
2. 中文分句优先于固定字数切断
3. 表格和正文分离
4. 不同文档类型使用不同默认策略
5. 每个 chunk 必须带足够元数据，便于检索解释和后续引用
6. chunk 预算采用“双阈值：字符 + token 估算”

### 建议阈值

- `soft_limit_chars = 900`
- `hard_limit_chars = 1400`
- `soft_limit_tokens = 600`
- `hard_limit_tokens = 900`
- `min_merge_chars = 220`
- `overlap_chars = 120`

这些值不是最终常量，但足够作为 v1 默认值与回归基线。

### 二级切分规则

当结构边界内的内容仍超过预算时，进入二级切分：

1. 长中文段落
- 先按自然段切
- 再按句号、分号、顿号附近切
- 最后才按长度硬切

2. 超宽表格
- 以表头为锚点
- 按行块切分
- 每个 chunk 重复列头，避免脱离上下文

3. 单页超长 PPT 备注
- slide 不跨页
- 页内备注按段落和句界二级切分
- 仍保留相同 `slide_number`

### 按格式的规则

#### PDF / DOCX
- 以标题层级、章节边界、自然段为主切分。
- 标题默认开启新 section。
- 段落累计到 `soft_limit_chars` 附近时优先收束。
- 超过 `hard_limit_chars` 时，再按中文句界细切。

#### PPTX
- 默认按 slide 切。
- 单页内容较少时允许同页文本合并，但不跨页。
- 标题、要点列表、备注分层处理。

#### XLSX
- 默认按 `sheet -> 表块` 切。
- 表头与表体保持在同一 chunk。
- 大表按行块切分，但保留列头。
- 单元格文本不会直接拼成无限长段落。

### 表格策略

- 表格独立 chunk，不与正文混合。
- 存储表名、页码/slide/sheet 信息。
- 文本化时优先保留：
  - 表标题
  - 列头
  - 关键行内容

## 上传接口设计

### 新接口

1. `POST /api/v1/knowledge/uploads`
- `multipart/form-data`
- 字段：
  - `workspace_id`
  - `scope`
  - `file`

2. `GET /api/v1/knowledge/uploads/{id}`
- 返回上传状态、解析摘要、chunk 数量、失败原因
- 返回 `storage_path`、原始文件名、source_type，便于排查

3. `GET /api/v1/knowledge/search`
- 继续复用现有接口，但响应项改为 `ChunkSearchHit`
- 不再从文档模型反查结果，而是从 chunk 持久化记录组装结果

## 旧文档兼容策略

必须在首轮实现里二选一明确落地，不能只停留在设计层：

1. 迁移策略
- 启动时把现有 `KnowledgeDocumentRecord` 回填为单 chunk 的 `KnowledgeChunkRecord`
- 新旧文档统一走 chunk 检索

2. 装配兼容策略
- 搜索装配层同时兼容 `document` 与 `chunk` 两类命中来源
- 旧数据继续返回，但响应统一映射成 `ChunkSearchHit`

本期推荐第 1 种：对现有 seed/旧文档做单 chunk 回填，避免后续维护两套搜索装配逻辑。

### 保留接口

- `POST /api/v1/knowledge/documents` 保留为纯文本快捷导入接口
- 适合测试、小样本文本、系统 seed 文档

## 前端范围

本期前端只补必要能力，不做完整知识库系统：

1. 上传入口
- 文件选择
- `workspace / scope` 选择
- 上传提交

2. 上传结果反馈
- 成功/失败状态
- 文档类型
- chunk 数量
- 解析摘要

3. 检索调试视图
- 展示命中的 chunk
- 展示标题、摘要、页码/slide/sheet、score

## 错误处理

### 错误分类

1. `unsupported_file_type`
2. `parse_failed`
3. `chunk_generation_failed`
4. `embedding_failed`
5. `index_upsert_failed`
6. `storage_failed`

### 处理原则

- 原始文件状态和索引状态分开记录
- 任何失败都要返回可诊断错误码
- 失败上传不写入半成状态 chunk
- 如果 Milvus 写入失败但 PostgreSQL 已写入，需要显式记录为 `index_pending` 或回滚

## 验证策略

### 样本文档集

至少准备以下样本：

1. 中文制度 PDF
2. 中英混排 DOCX
3. 多页销售 PPTX
4. 多 sheet 财务 XLSX
5. 含表格与标题层级的长文档 PDF

### 验证点

1. 解析成功率
2. chunk 数量是否合理
3. 是否出现明显超大 chunk
4. 表格是否被错误混入正文
5. 检索命中是否能定位到正确 section/page/slide/sheet
6. workspace/shared 隔离是否保持正确
7. 长中文段落、超宽表格、超长 PPT 备注是否会触发二级切分
8. 端到端链路 `上传 -> 存储 -> 解析 -> chunk -> 索引 -> 搜索` 是否对真实样本成立

## 分阶段落地

### Phase 1
- 引入 `ChunkSearchHit`，先重构搜索返回链路
- 引入 `DoclingParserAdapter`
- 建立 `CanonicalBlock` 与 `ChunkRecord`
- 支持 `PDF / DOCX / PPTX / XLSX`

### Phase 2
- `KnowledgeSourceFile` 与对象存储落地
- 前端上传页与检索调试视图
- Chunk trace 与上传状态可视化

### Phase 3
- OCR 强化
- 更细的 chunk 参数调优
- 文档预览与引用回跳

## 结论

本设计的核心不是“接一个能读文件的库”，而是把上传链路拆成：

- `解析`
- `标准化`
- `结构化切分`
- `索引`

其中 `Docling` 解决解析能力，`structure-aware chunker` 解决中文与结构质量，现有 `Qwen embedding + Milvus` 继续承担检索层。

这条路线在当前代码库内改动可控，能真正解决“上传后检索质量差、chunk 过大、格式信息丢失”的主要问题。
