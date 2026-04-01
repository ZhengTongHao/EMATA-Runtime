export function buildKnowledgeConsoleViewModel({ workspaces = [], indexStatus = null } = {}) {
  const workspaceOptions = (workspaces.length ? workspaces : fallbackWorkspaces()).map(
    (workspace) => ({
      id: workspace.id,
      label: workspace.name || workspace.id,
      description: workspace.description || "受控知识空间",
    }),
  );
  const knowledgeIndexStatus = buildKnowledgeIndexStatusViewModel(indexStatus);

  return {
    title: "知识库操作台",
    subtitle:
      "在同一页里完成文件上传、状态确认和 chunk 级检索调试，先把真实知识链路跑通，再逐步补充批量导入和历史视图。",
    uploadHeading: "上传知识",
    uploadHint:
      "当前支持 TXT、DOCX、PPTX、XLSX 直接入库；PDF 走 MinerU 解析链路，运行环境需要可执行的 MinerU CLI。",
    searchHeading: "检索知识",
    searchHint:
      "查询结果会保留 chunk、章节、页码、sheet 和 slide 等定位元数据，并展示本次检索轨迹。",
    sampleQueries: ["报销审批", "ERP 风险", "discount battlecard"],
    supportedFormats: ["TXT", "DOCX", "PPTX", "XLSX", "PDF"],
    fileAccept: ".txt,.docx,.pptx,.xlsx,.pdf",
    parserRoutes: [
      { label: "TXT", detail: "直接解析", tone: "ready" },
      { label: "DOCX", detail: "python-docx", tone: "ready" },
      { label: "PPTX", detail: "python-pptx", tone: "ready" },
      { label: "XLSX", detail: "openpyxl", tone: "ready" },
      { label: "PDF", detail: "MinerU CLI", tone: "conditional" },
    ],
    workspaceOptions,
    defaultWorkspaceId: workspaceOptions[0]?.id || "workspace-finance",
    uploadHistoryHeading: "最近上传",
    uploadHistoryHint: "保留最近的上传结果、失败原因和 chunk 统计，方便快速回看解析质量。",
    uploadTimeoutMs: 10 * 60 * 1000,
    searchTimeoutMs: 30 * 1000,
    indexStatus: knowledgeIndexStatus,
  };
}

export function renderKnowledgePagePreview(viewModel) {
  return `
    <main>
      <h1>${viewModel.title}</h1>
      <section>${viewModel.uploadHeading}</section>
      <section>${viewModel.searchHeading}</section>
      <section>${viewModel.indexStatus.value}</section>
      <aside>${viewModel.workspaceOptions.map((item) => item.label).join(",")}</aside>
    </main>
  `;
}

export function buildKnowledgeIndexStatusViewModel(status) {
  const payload = status || {};
  const isSdk = payload.backend_mode === "sdk";
  const endpoint = payload.endpoint ? ` @ ${payload.endpoint}` : "";
  const count = Number.isFinite(payload.indexed_record_count) ? payload.indexed_record_count : 0;
  return {
    key: "Index",
    value: isSdk ? "Milvus SDK" : "Fallback",
    description: isSdk
      ? `${payload.collection_name || "emata_documents"}${endpoint} · ${count} chunks`
      : `当前使用回退检索 · ${payload.backend_reason || "status_unavailable"}`,
    backendMode: payload.backend_mode || "fallback",
    backendReason: payload.backend_reason || "status_unavailable",
    collectionName: payload.collection_name || "emata_documents",
    collectionReady: Boolean(payload.collection_ready),
    indexedRecordCount: count,
    endpoint: payload.endpoint || "",
  };
}

export function formatSearchResultMeta(item) {
  const parts = [];
  if (item.block_type) {
    parts.push(item.block_type);
  }
  if (Array.isArray(item.section_path) && item.section_path.length) {
    parts.push(item.section_path.join(" / "));
  }
  if (item.page_number && item.page_end && item.page_end !== item.page_number) {
    parts.push(`P.${item.page_number}-${item.page_end}`);
  } else if (item.page_number) {
    parts.push(`P.${item.page_number}`);
  }
  if (item.sheet_name) {
    parts.push(item.sheet_name);
  }
  if (item.slide_number) {
    parts.push(`Slide ${item.slide_number}`);
  }
  return parts.join(" · ");
}

export function formatSearchTraceSummary(trace) {
  if (!trace) {
    return "尚未开始检索。";
  }

  const backendLabel =
    trace.backend_mode === "sdk"
      ? "Milvus"
      : trace.backend_mode === "document-store"
        ? "Document Store"
        : "Fallback";
  const rewriteLabel = trace.rewrite_applied ? "已启用改写" : "未触发改写";
  const variantLabel = `${trace.query_variants?.length || 1} 个查询版本`;
  const reason = trace.backend_reason ? `，原因：${trace.backend_reason}` : "";
  return `${backendLabel} · ${rewriteLabel} · ${variantLabel} · ${trace.result_count} 条命中${reason}`;
}

export function formatSearchResultExplanation(item) {
  if (!item) {
    return "";
  }

  const parts = [];
  if (item.matched_query) {
    parts.push(`命中查询：${item.matched_query}`);
  }
  if (Array.isArray(item.matched_terms) && item.matched_terms.length) {
    parts.push(`命中词：${item.matched_terms.join(", ")}`);
  }
  if (item.parser_backend) {
    parts.push(formatParserBackend(item.parser_backend));
  }

  const locationSummary = formatSearchResultMeta(item);
  if (locationSummary) {
    parts.push(locationSummary);
  }
  return parts.join(" · ");
}

export function getSearchSubmitLabel({ isRequesting }) {
  return isRequesting ? "检索中..." : "开始检索";
}

export function getUploadSubmitLabel({ isSubmitting }) {
  return isSubmitting ? "上传中..." : "开始上传";
}

export function formatKnowledgeErrorMessage(message) {
  if (!message) {
    return "请求失败，请稍后重试。";
  }
  if (message === "request_canceled") {
    return "已取消本次请求。";
  }
  if (message === "search_canceled") {
    return "服务端已停止继续处理这次检索。";
  }
  if (message === "upload_canceled") {
    return "服务端已停止继续处理这次上传。";
  }
  if (message === "request_timeout" || message === "parse_timeout") {
    return "请求超时，请稍后重试。";
  }
  if (message === "mineru_executable_not_found") {
    return "未找到 MinerU CLI，当前环境暂时无法解析 PDF。";
  }
  if (message === "invalid_pdf_file") {
    return "PDF 鏂囦欢鏃犳晥鎴栧凡鎹熷潖锛岃鏇存崲涓€浠界湡瀹炲彲鎵撳紑鐨?PDF 鍚庡啀涓婁紶銆?";
  }
  if (message.startsWith("parse_failed:")) {
    const detail = message.split(":").slice(2).join(":");
    return detail ? `PDF 解析失败：${detail}` : "PDF 解析失败，请检查 MinerU 运行环境。";
  }
  if (message.startsWith("upload_processing_failed:")) {
    return "上传处理失败，请检查服务日志或依赖环境。";
  }
  if (message === "workspace_access_denied") {
    return "当前账号没有该 Workspace 的访问权限。";
  }
  return message;
}

export function formatUploadFailureReason(item) {
  return formatKnowledgeErrorMessage(item?.error_code || item?.error_message || "");
}

export function formatUploadHistoryMeta(item) {
  const parts = [];
  if (item.source_type) {
    parts.push(item.source_type.toUpperCase());
  }
  parts.push(item.scope === "shared" ? "Organization Shared" : "Workspace Private");
  if (typeof item.chunk_count === "number") {
    parts.push(`${item.chunk_count} chunks`);
  }
  if (item.created_at) {
    parts.push(formatTimestamp(item.created_at));
  }
  return parts.join(" · ");
}

export function formatUploadHistorySummary(item) {
  const summary = item?.ingestion_summary;
  if (!summary) {
    return "";
  }

  const parts = [];
  const parserLabel = formatParserBackend(summary.parser_backend);
  if (parserLabel) {
    parts.push(parserLabel);
  }
  if (summary.page_start && summary.page_end) {
    parts.push(
      summary.page_start === summary.page_end
        ? `P.${summary.page_start}`
        : `P.${summary.page_start}-${summary.page_end}`,
    );
  } else if (summary.page_start) {
    parts.push(`P.${summary.page_start}`);
  }
  if (Array.isArray(summary.section_samples) && summary.section_samples.length) {
    parts.push(summary.section_samples.slice(0, 2).join(" | "));
  }
  if (Array.isArray(summary.block_types) && summary.block_types.length) {
    parts.push(`Blocks: ${summary.block_types.join(", ")}`);
  }
  return parts.join(" · ");
}

function formatTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toISOString().slice(0, 16).replace("T", " ");
}

function fallbackWorkspaces() {
  return [
    { id: "workspace-finance", name: "Finance", description: "Finance operations workspace." },
    { id: "workspace-sales", name: "Sales", description: "Sales operations workspace." },
  ];
}

function formatParserBackend(value) {
  if (!value) {
    return "";
  }
  if (value === "mineru") {
    return "MinerU";
  }
  if (value === "manual") {
    return "Manual";
  }
  return String(value).toUpperCase();
}
