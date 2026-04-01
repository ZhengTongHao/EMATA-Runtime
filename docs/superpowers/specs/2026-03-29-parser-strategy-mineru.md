# PDF MinerU + Office Native Parser Design

## Goal

把 EMATA 的文档解析策略从“统一 Docling”调整为“PDF 走 MinerU，Office 文档走原生解析”。

这次调整的目标不是推翻现有上传链路，而是让后续多格式接入更适配当前仓库的技术现实：

- `PDF` 优先解决 OCR、版面、表格和中文扫描件问题
- `DOCX / PPTX / XLSX` 优先用轻量、稳定、易调试的原生库
- 上层继续复用已有的 `CanonicalBlock -> ChunkPolicyEngine -> EmbeddingProvider -> Milvus`

## Why Change

原方案默认用 `Docling` 统一吃下所有格式，但当前代码库仍然运行在：

- `FastAPI 0.95`
- `Pydantic 1.10.x`

而 `Docling` 路线在当前环境里已经暴露出依赖冲突风险，不适合作为下一阶段的低风险主方案。

另一方面，用户明确倾向：

- `PDF` 采用 OCR 策略
- `PDF` 优先接 `MinerU`

所以本期设计改为按文档类型分治，而不是坚持统一解析器。

## Chosen Architecture

```text
TXT   -> TxtParserAdapter
PDF   -> MinerUPdfParserAdapter
DOCX  -> DocxParserAdapter
PPTX  -> PptxParserAdapter
XLSX  -> XlsxParserAdapter
      -> CanonicalBlock
      -> ChunkPolicyEngine
      -> PostgreSQL snapshot persistence
      -> Qwen Embedding
      -> Milvus
```

### Parser Boundaries

1. `DocumentParserAdapter`
- 统一接口：`parse_file(file_path, source_type) -> list[CanonicalBlock]`
- 不关心 chunk，不直接碰 Milvus

2. `DocumentParserRegistry`
- 按 `source_type` 选择对应 parser
- 允许后续扩展 `html`、`md`、`image` 等类型

3. `MinerUPdfParserAdapter`
- 仅负责 PDF
- 通过 CLI 调用 `MinerU`
- 默认策略用 `auto`
- 把 `MinerU` 输出映射为 `CanonicalBlock`

4. `DocxParserAdapter`
- 通过 `python-docx` 解析段落和标题
- 保留标题层级和段落顺序

5. `PptxParserAdapter`
- 通过 `python-pptx` 按 slide 读取
- 保留 `slide_number`
- 标题与正文分开建块

6. `XlsxParserAdapter`
- 通过 `openpyxl` 按 `sheet -> row block` 读取
- 保留 `sheet_name`
- 表头和数据行保持可组合的结构块

## PDF Strategy

### Why MinerU

`MinerU` 更适合当前 PDF 目标：

- 支持 `ocr / txt / auto`
- 更偏向复杂 PDF、表格、版面理解
- 能输出结构化结果，便于映射到 `CanonicalBlock`

### Integration Principles

- 不把 `MinerU` 输出直接当最终 chunk
- 先做 `MinerU -> CanonicalBlock`
- 再走现有 `ChunkPolicyEngine`

### Runtime Contract

环境变量建议：

- `EMATA_MINERU_EXECUTABLE=mineru`
- `EMATA_MINERU_METHOD=auto`
- `EMATA_MINERU_OUTPUT_FORMAT=json`

如果 `MinerU` 不可用：

- 不 silent fallback 成纯空结果
- 明确抛出 `parse_failed`
- 在上传状态里保留错误码和错误信息

## Office Strategy

### DOCX

- 使用 `python-docx`
- 标题样式映射为 `heading`
- 普通段落映射为 `paragraph`

### PPTX

- 使用 `python-pptx`
- 每页默认至少形成一个独立 slide 边界
- 标题映射为 `heading`
- 其他文本框映射为 `slide`

### XLSX

- 使用 `openpyxl`
- 每个 sheet 独立作用域
- 表头和若干数据行组成 `table` 或 `sheet` block
- 不把整张表直接摊平成单个超长文本

## Compatibility With Current System

保持不变：

- 上传 API 契约
- `KnowledgeSourceFile`
- `KnowledgeChunkRecord`
- `ChunkPolicyEngine`
- `EmbeddingProvider`
- `MilvusKnowledgeIndex`

需要替换/新增：

- 现有 [document_ingestion.py](/E:/Project/Agent/backend/app/document_ingestion.py) 中的单一 `DoclingParserAdapter`
- 新增 parser registry 和各格式 adapter
- 新增 `MinerU` 相关配置与运行时探测

## Testing Strategy

### Unit

- `DOCX` 标题/段落可正确映射
- `PPTX` slide 边界不串页
- `XLSX` sheet 边界不串 sheet
- `PDF` 的 `MinerU` 适配器能把 mock 输出映射为 `CanonicalBlock`

### Integration

- 上传 `docx/pptx/xlsx` 后能产生 chunk
- chunk 元数据带上 `section_path / slide_number / sheet_name`
- `PDF` 在 `MinerU` 可用时能产出结构块

### Live

- `TXT` 现有链路不回归
- 新增样本文档上传后能被搜索命中
- workspace/shared 隔离保持成立

## Risks

1. `MinerU` 运行时较重
- 本期先走 CLI 适配，不直接把其 Python 依赖嵌进主 API

2. PDF 结构输出不稳定
- 通过 adapter 层统一和收敛

3. Office 文档格式差异
- 先覆盖常见标题/段落/文本框/worksheet 场景
- 极复杂样式放到后续增强

## Decision

下一阶段正式采用：

- `PDF -> MinerU`
- `DOCX -> python-docx`
- `PPTX -> python-pptx`
- `XLSX -> openpyxl`

不再把 `Docling` 作为当前主实施路线。
