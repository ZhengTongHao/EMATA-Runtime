export function buildAskPageViewModel({ workspaces = [], samplePrompts } = {}) {
  return {
    title: "Ask Copilot Workbench",
    subtitle:
      "统一的 Ask 对话入口。当前先激活 HR Recruiting Skill，同时保留知识检索、文档产物和飞书工具扩展位。",
    samplePrompts: samplePrompts || [],
    workspaceLabels: (workspaces || []).map((item) => item.name || item.id),
    defaultSkillId: "hr_recruiting",
    defaultTitle: "Ask Copilot",
    emptyState:
      "会话创建后，这里会保留多轮上下文、知识引用和动作确认流。你可以直接输入自然语言指令。",
  };
}

export function renderAskPagePreview(viewModel) {
  return `
    <main>
      <h1>${viewModel.title}</h1>
      <p>${viewModel.subtitle}</p>
    </main>
  `;
}

export function formatAskOutputLabel(type) {
  if (type === "message") {
    return "答复";
  }
  if (type === "citation") {
    return "引用";
  }
  if (type === "card") {
    return "确认卡";
  }
  if (type === "artifact") {
    return "产物";
  }
  if (type === "tool_result") {
    return "执行结果";
  }
  return "输出";
}

export function partitionTurnOutputs(outputs = []) {
  const primaryOutputs = [];
  const citationOutputs = [];

  for (const output of outputs) {
    if (output?.type === "citation") {
      citationOutputs.push(output);
    } else {
      primaryOutputs.push(output);
    }
  }

  return {
    primaryOutputs,
    citationOutputs,
  };
}

export function getTargetSelectionOptions(output) {
  return output?.data?.options || [];
}

export function buildTargetSelectionModel(output) {
  const searchResults = output?.data?.search_results || {};
  const options = getTargetSelectionOptions(output);
  return {
    contacts: searchResults.contacts || [],
    chats: searchResults.chats || [],
    options,
    otherOption: options.find((option) => option.kind === "other") || null,
  };
}

export function buildActionPreviewModel(output) {
  const draft = output?.data?.draft || {};
  const resolvedTarget = draft.resolved_target || {};
  return {
    editable: Boolean(output?.data?.editable),
    summary: draft.summary || "",
    text: draft.text || "",
    targetLabel: resolvedTarget.label || draft.target_query || "",
    editableFields: draft.editable_fields || [],
    actions: draft.actions || [],
  };
}

export function formatAskErrorMessage(message) {
  if (!message) {
    return "请求失败，请稍后重试。";
  }
  if (message === "request_canceled") {
    return "这次请求已取消。";
  }
  if (message === "request_timeout") {
    return "请求超时，请稍后再试。";
  }
  if (message === "ask_session_not_found") {
    return "当前会话不存在，建议刷新后重试。";
  }
  if (message === "feishu_cli_not_configured") {
    return "后端还没有配置飞书应用凭据，暂时无法发起绑定。";
  }
  if (message === "feishu_device_code_required") {
    return "缺少绑定校验码，请重新发起飞书绑定。";
  }
  if (message === "feishu_cli_not_found") {
    return "当前环境没有安装 lark-cli，暂时无法接通飞书。";
  }
  return message;
}

export function formatToolResultSummary(output) {
  const data = output?.data || {};
  const result = data.result || {};
  const preview = data.preview || {};
  const capability = preview.capability || result.capability || "";
  const summary = result.summary || "";
  const link = result.result_link || "";
  const externalId = result.external_id || "";
  return [summary || capability, externalId, link].filter(Boolean).join(" · ");
}

export function formatToolResultError(output) {
  const result = output?.data?.result || {};
  if (result.status !== "failed") {
    return "";
  }
  return result.error_message || result.error_code || "";
}

export function formatAskJobStatus(status) {
  if (status === "pending") {
    return "排队中";
  }
  if (status === "running") {
    return "执行中";
  }
  if (status === "finished") {
    return "已完成";
  }
  if (status === "failed") {
    return "执行失败";
  }
  return status || "未知";
}

export function formatFeishuBindingStatus(binding) {
  if (!binding) {
    return "未绑定";
  }
  if (binding.status === "ACTIVE") {
    return binding.identity?.user_name ? `已绑定：${binding.identity.user_name}` : "已绑定";
  }
  if (binding.status === "PENDING") {
    return "绑定中";
  }
  if (binding.status === "REAUTH_REQUIRED") {
    return "需要重新授权";
  }
  return "未绑定";
}

export function formatFeishuBindingHint(binding) {
  if (!binding) {
    return "绑定飞书后，Ask 才能真正读取日历、文档和消息能力。";
  }
  if (binding.status === "REAUTH_REQUIRED") {
    return (
      binding.hint ||
      "当前本地飞书授权不可用，请重新授权或切换账号。完成后 Ask 会自动恢复可用状态。"
    );
  }
  if (binding.status === "ACTIVE" && !(binding.missing_scopes || []).length) {
    return "当前飞书身份已可用于安排面试、生成文档和内部协同。";
  }
  if (binding.status === "PENDING") {
    return "授权页打开后，先在飞书完成授权。Ask 会自动继续检查绑定状态，你也可以手动刷新。";
  }
  if ((binding.missing_scopes || []).length) {
    if ((binding.missing_scopes || []).includes("im:chat:read")) {
      return "当前还缺少 im:chat:read。要支持发到群和按群名检索，请在飞书应用里开通这条权限后重新绑定。";
    }
    if ((binding.missing_scopes || []).includes("search:message")) {
      return "当前还缺少 search:message。要解析外部联系人或已有私聊会话，请在飞书应用里开通这条权限后重新绑定。";
    }
    return `还缺少权限：${binding.missing_scopes.join("、")}`;
  }
  return "绑定飞书后，Ask 才能真正读取日历、文档和消息能力。";
}
