import test from "node:test";
import assert from "node:assert/strict";

import {
  buildKnowledgeIndexStatusViewModel,
  buildKnowledgeConsoleViewModel,
  formatKnowledgeErrorMessage,
  formatSearchResultExplanation,
  formatSearchTraceSummary,
  formatUploadFailureReason,
  formatUploadHistoryMeta,
  formatUploadHistorySummary,
  getSearchSubmitLabel,
  getUploadSubmitLabel,
  renderKnowledgePagePreview,
} from "../lib/knowledge.js";

test("knowledge page renders upload and search panels", () => {
  const viewModel = buildKnowledgeConsoleViewModel({
    workspaces: [{ id: "workspace-finance", name: "Finance", description: "Finance ops" }],
    indexStatus: {
      backend_mode: "sdk",
      backend_reason: "available",
      collection_name: "emata_documents",
      indexed_record_count: 12,
      endpoint: "127.0.0.1:19530",
    },
  });

  const html = renderKnowledgePagePreview(viewModel);

  assert.match(html, /知识库操作台/);
  assert.match(html, /上传知识/);
  assert.match(html, /检索知识/);
  assert.match(html, /Milvus SDK/);
  assert.match(html, /Finance/);
});

test("knowledge index status view model highlights Milvus SDK and chunk count", () => {
  const status = buildKnowledgeIndexStatusViewModel({
    backend_mode: "sdk",
    backend_reason: "available",
    collection_name: "emata_documents",
    collection_ready: true,
    indexed_record_count: 18,
    endpoint: "127.0.0.1:19530",
  });

  assert.equal(status.value, "Milvus SDK");
  assert.match(status.description, /emata_documents/);
  assert.match(status.description, /18 chunks/);
  assert.match(status.description, /127\.0\.0\.1:19530/);
});

test("search trace summary highlights backend and rewrite status", () => {
  const summary = formatSearchTraceSummary({
    backend_mode: "fallback",
    backend_reason: "endpoint_unreachable",
    query_variants: ["ERP 审批", "ERP 审批 enterprise resource planning authorize review"],
    result_count: 3,
    rewrite_applied: true,
  });

  assert.match(summary, /Fallback/i);
  assert.match(summary, /改写/);
  assert.match(summary, /3/);
  assert.match(summary, /2 个查询版本/);
});

test("search result explanation summarizes matched query, terms, parser and location", () => {
  const summary = formatSearchResultExplanation({
    matched_query: "ERP 审批 enterprise resource planning authorize review",
    matched_terms: ["ERP", "审批"],
    parser_backend: "mineru",
    block_type: "paragraph",
    section_path: ["审批流程"],
    page_number: 2,
    page_end: 4,
  });

  assert.match(summary, /ERP/);
  assert.match(summary, /MinerU/i);
  assert.match(summary, /paragraph/);
  assert.match(summary, /P\.2-4/);
});

test("knowledge console view model advertises multi-format ingestion support", () => {
  const viewModel = buildKnowledgeConsoleViewModel({
    workspaces: [{ id: "workspace-finance", name: "Finance", description: "Finance ops" }],
  });

  assert.equal(viewModel.fileAccept, ".txt,.docx,.pptx,.xlsx,.pdf");
  assert.deepEqual(viewModel.supportedFormats, ["TXT", "DOCX", "PPTX", "XLSX", "PDF"]);
  assert.match(viewModel.uploadHint, /DOCX/);
  assert.match(viewModel.uploadHint, /MinerU/i);
});

test("search submit label reflects real request state", () => {
  assert.equal(getSearchSubmitLabel({ isRequesting: true }), "检索中...");
  assert.equal(getSearchSubmitLabel({ isRequesting: false }), "开始检索");
});

test("upload submit label reflects request state", () => {
  assert.equal(getUploadSubmitLabel({ isSubmitting: true }), "上传中...");
  assert.equal(getUploadSubmitLabel({ isSubmitting: false }), "开始上传");
});

test("knowledge error formatter explains parser and timeout failures", () => {
  assert.match(formatKnowledgeErrorMessage("parse_timeout"), /超时/);
  assert.match(formatKnowledgeErrorMessage("parse_failed:7:pipeline exploded"), /pipeline exploded/);
  assert.match(formatKnowledgeErrorMessage("mineru_executable_not_found"), /MinerU/i);
  assert.match(formatKnowledgeErrorMessage("request_canceled"), /取消/);
  assert.match(formatKnowledgeErrorMessage("search_canceled"), /服务端已停止继续处理这次检索/);
});

test("upload history meta includes format, scope, chunk count and timestamp", () => {
  const summary = formatUploadHistoryMeta({
    source_type: "pdf",
    scope: "workspace",
    chunk_count: 12,
    created_at: "2026-03-30T01:00:00Z",
  });

  assert.match(summary, /PDF/);
  assert.match(summary, /12/);
  assert.match(summary, /Workspace/);
  assert.match(summary, /2026/);
});

test("upload history summary explains parser, page span, sections and block types", () => {
  const summary = formatUploadHistorySummary({
    ingestion_summary: {
      parser_backend: "mineru",
      page_start: 1,
      page_end: 3,
      section_samples: ["第一章 总则", "第一章 总则 / 审批流程"],
      block_types: ["paragraph", "table"],
    },
  });

  assert.match(summary, /MinerU/i);
  assert.match(summary, /P\.1-3/);
  assert.match(summary, /第一章 总则/);
  assert.match(summary, /paragraph/);
  assert.match(summary, /table/);
});

test("upload failure reason prefers error code over raw message", () => {
  const summary = formatUploadFailureReason({
    error_code: "parse_timeout",
    error_message: "Traceback: raw parser stack",
  });

  assert.match(summary, /超时/);
  assert.doesNotMatch(summary, /Traceback/);
});
test("knowledge error formatter explains invalid pdf payloads", () => {
  assert.match(formatKnowledgeErrorMessage("invalid_pdf_file"), /PDF/);
});
