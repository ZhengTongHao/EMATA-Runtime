# MinerU And Office Native Parsers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 EMATA 接入 `PDF -> MinerU` 与 `DOCX/PPTX/XLSX -> 原生解析` 的多格式文档解析能力。

**Architecture:** 保留现有上传、chunk、embedding、Milvus 链路，只替换解析层。新增 parser registry；PDF 通过 MinerU CLI 适配为 `CanonicalBlock`；Office 文档通过原生库解析为结构块。

**Tech Stack:** Python, FastAPI, python-docx, python-pptx, openpyxl, MinerU CLI, PostgreSQL snapshot store, Milvus

---

## File Structure

- Modify: `E:/Project/Agent/backend/app/document_ingestion.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/requirements-optional.txt`
- Modify: `E:/Project/Agent/environment.yml`
- Modify: `E:/Project/Agent/.env.example`
- Modify: `E:/Project/Agent/README.md`
- Modify: `E:/Project/Agent/backend/tests/test_document_ingestion.py`
- Modify: `E:/Project/Agent/backend/tests/test_upload_api.py`

### Task 1: 引入 parser registry 和 Office 解析测试

**Files:**
- Modify: `E:/Project/Agent/backend/tests/test_document_ingestion.py`
- Modify: `E:/Project/Agent/backend/app/document_ingestion.py`

- [ ] **Step 1: 先写失败测试，约束 DOCX / PPTX / XLSX 解析输出**
- [ ] **Step 2: 运行单测确认失败**
- [ ] **Step 3: 实现 `TxtParserAdapter / DocxParserAdapter / PptxParserAdapter / XlsxParserAdapter / DocumentParserRegistry`**
- [ ] **Step 4: 运行单测确认通过**

### Task 2: 把上传链路切到 registry

**Files:**
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/tests/test_upload_api.py`

- [ ] **Step 1: 先写失败测试，约束 DOCX/PPTX/XLSX 能进入 parse 流程**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 在 `ServiceContainer` 中改用 registry，而不是单一 parser**
- [ ] **Step 4: 运行测试确认通过**

### Task 3: 接入 MinerU PDF 适配器

**Files:**
- Modify: `E:/Project/Agent/backend/app/document_ingestion.py`
- Modify: `E:/Project/Agent/.env.example`
- Modify: `E:/Project/Agent/backend/tests/test_document_ingestion.py`

- [ ] **Step 1: 先写失败测试，约束 `MinerUPdfParserAdapter` 可把 CLI 输出映射为 `CanonicalBlock`**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 `MinerUPdfParserAdapter` 和配置项**
- [ ] **Step 4: 运行测试确认通过**

### Task 4: 依赖、说明和回归验证

**Files:**
- Modify: `E:/Project/Agent/backend/requirements-optional.txt`
- Modify: `E:/Project/Agent/environment.yml`
- Modify: `E:/Project/Agent/README.md`

- [ ] **Step 1: 补充 Office 解析依赖和 MinerU 配置说明**
- [ ] **Step 2: 运行后端关键测试**
- [ ] **Step 3: 如环境允许，做一轮 live 上传验证**
