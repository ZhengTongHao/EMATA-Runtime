# EMATA Handoff - 2026-03-30

## 1. PRD Baseline

来源文件：`D:\笔记\enterprise_multi_agent_prd.md`

本仓库后续工作默认继续遵守以下 PRD 基线：

- 产品：`Enterprise Multi-Agent Task Assistant (EMATA)`
- 目标：企业级多 Agent 协同、流程自动化、知识增强、跨系统执行
- 核心模块：
  - `Planner Agent`
  - `Worker Agent`
  - `Orchestrator Agent`
  - `Skills`
  - `RAG / Knowledge Agent`
  - `UI / Dashboard`
- 关键集成：
  - `Feishu`
  - `ERP`
  - `CRM`
  - `Email`
  - `Vector DB`
- 关键方向：
  - 多 Agent 协作
  - RAG + 向量检索
  - Skills 模块化
  - 跨系统任务自动化
  - 可视化监控与量化指标

结合当前已定架构，继续按这些约束推进：

- 暂停 Docker 收口，先把本地功能做全、做稳
- `PDF -> MinerU`
- `DOCX/PPTX/XLSX -> 原生解析`
- `Qwen Embedding + Milvus`
- 上传、chunk、检索、前端交互优先于部署封装

## 2. Current Phase

当前阶段状态：

- `PDF/MinerU 解析质量与 chunk 策略`：已完成并通过 reviewer
- `知识库上传页：上传历史、失败原因、ingestion_summary`：已完成并通过 reviewer
- 当前正在进行：`知识检索质量提升：trace / query rewrite / 结果解释`
- 明确追加目标：`RAG rerank` 必做，但排在“检索解释已清晰”之后

## 3. What Is Done

### 3.1 PDF / MinerU

关键文件：

- [document_ingestion.py](/E:/Project/Agent/backend/app/document_ingestion.py)
- [test_document_ingestion.py](/E:/Project/Agent/backend/tests/test_document_ingestion.py)

已完成：

- 优先解析 MinerU 的 structured JSON，而不是 markdown
- 支持两种 structured 输出：
  - `content_list_v2.json` 的按页嵌套结构
  - `content_list.json` 的 flat 结构，按 `page_idx/page_number/page_no/page` 归页
- structured JSON 解码失败、schema 异常或无有效块时，回退到 markdown
- `第X条` 规则已细化：
  - 长引导句降级为 `paragraph`
  - 短条级标题保留为三级 section anchor
- chunk anchor 页码使用组起始页
- chunk metadata 保留 parser/source_type，并写入 `page_end`

真实样本验证：

- 样本文件：`E:\Project\Agent\tmp\pdfs\ndrc-sample.pdf`
- 本地 MinerU CLI 可正常跑通
- 当前真实样本结果：
  - 章节 heading 提取正常
  - 误判的长条文标题已被压回 paragraph
  - chunk 页码范围不再因“起始页语义”而失真

### 3.2 Upload History / Failure Reason / Ingestion Summary

关键文件：

- [contracts.py](/E:/Project/Agent/backend/app/contracts.py)
- [routes.py](/E:/Project/Agent/backend/app/routes.py)
- [services.py](/E:/Project/Agent/backend/app/services.py)
- [knowledge-upload-form.js](/E:/Project/Agent/frontend/components/knowledge-upload-form.js)
- [knowledge.js](/E:/Project/Agent/frontend/lib/knowledge.js)
- [test_upload_api.py](/E:/Project/Agent/backend/tests/test_upload_api.py)
- [knowledge-page.test.mjs](/E:/Project/Agent/frontend/tests/knowledge-page.test.mjs)

已完成：

- `POST /api/v1/knowledge/uploads`
- `GET /api/v1/knowledge/uploads`
- `GET /api/v1/knowledge/uploads/{id}`

以上三个接口现在都会返回 `ingestion_summary`，包含：

- `parser_backend`
- `page_start`
- `page_end`
- `section_samples`
- `block_types`

前端知识页现在会展示：

- 上传成功态的 ingestion summary
- 最近上传历史
- 失败原因
- 失败项优先按 `error_code` 做用户态分层提示，不优先暴露原始异常文本

## 4. Verification Evidence

最近一次完整验证通过：

### Backend

命令：

```powershell
& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_document_ingestion tests.test_upload_api tests.test_integrations -v
```

结果：

- `63` tests passed

### Frontend

命令：

```powershell
node --test frontend/tests/dashboard.test.mjs frontend/tests/knowledge-page.test.mjs
```

结果：

- `10` tests passed

### Build

命令：

```powershell
npm run build
```

目录：

- `E:\Project\Agent\frontend`

结果：

- `Next.js build` passed

## 5. Reviewer Status

当前已通过的 reviewer 阶段：

1. `PDF/MinerU 解析与 chunk 锚点修正`
2. `上传历史 / 失败原因 / ingestion_summary`

最新 reviewer 结论：`通过`

## 6. Known Constraints

- 当前仍然**不继续做 Docker 收口**
- Docker 相关代码和配置保留兼容性，但不是当前优先级
- 工作树很脏，存在大量与本任务无关的历史改动
- 不要回滚无关文件
- 当前环境里：
  - `MinerU CLI` 可本地使用
  - `Miniconda + emata` 环境可跑后端测试

## 7. Exact Next Step

下一步直接继续：

### 检索解释优化

目标：

- 把现有 `trace`
- `query rewrite`
- `chunk 命中元数据`
- `ingestion_summary`

整理成更易读的前端结果解释

建议执行顺序：

1. 先梳理当前搜索接口返回内容和前端展示缺口
2. 增加“为什么命中”解释层
3. 把 `query_variants / backend_mode / rewrite_applied / chunk location` 转成用户可读摘要
4. 再引入 `RAG rerank`
5. 最后补排序质量验证

## 8. Rerank Requirement

用户已明确要求：

- `RAG rerank` 必做

当前约定：

- 先把检索解释和现有召回观察清楚
- 再接 rerank
- 避免把“召回问题”和“排序问题”混在同一步处理

## 9. Resume Instructions For New Thread

新线程开始时直接做这几步：

1. 读取本文件
2. 继续执行“检索解释优化”
3. 完成后按既定闭环：
   - 主线程实现
   - reviewer 子线程审查
   - 不通过只修明确问题
   - 通过后进入 `RAG rerank`

