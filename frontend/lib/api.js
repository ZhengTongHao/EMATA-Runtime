export function resolveApiBaseUrl(env = process.env) {
  const raw =
    env.NEXT_PUBLIC_EMATA_API_BASE_URL ||
    env.EMATA_API_BASE_URL ||
    "http://localhost:8000";

  return String(raw).trim().replace(/\s*\/+\s*$/, "").trim();
}

const API_BASE_URL = resolveApiBaseUrl();

const fallbackRuns = [
  {
    id: "run-sample-approval",
    title: "ERP sync needs approval",
    status: "WAITING_APPROVAL",
    workspace_id: "workspace-finance",
    requested_capability: "erp.write",
    goal: "Push the approved order update into ERP.",
  },
  {
    id: "run-sample-report",
    title: "Daily risk summary",
    status: "RUNNING",
    workspace_id: "workspace-finance",
    requested_capability: "report.generate",
    goal: "Generate a risk summary for morning review.",
  },
  {
    id: "run-sample-crm",
    title: "CRM writeback retry",
    status: "FAILED",
    workspace_id: "workspace-sales",
    requested_capability: "crm.write",
    goal: "Sync the latest lead changes to CRM.",
  },
];

const fallbackWorkspaces = [
  {
    id: "workspace-finance",
    organization_id: "org-acme",
    name: "Finance",
    description: "Finance operations workspace.",
  },
  {
    id: "workspace-sales",
    organization_id: "org-acme",
    name: "Sales",
    description: "Sales operations workspace.",
  },
];

export const ASK_TURN_TIMEOUT_MS = 60000;
export const ASK_COMMAND_TIMEOUT_MS = 120000;

export function buildAskJobStatusUrl(jobId) {
  return `${API_BASE_URL}/api/v1/ask/jobs/${jobId}`;
}

export function buildAskJobEventsUrl(jobId) {
  return `${API_BASE_URL}/api/v1/ask/jobs/${jobId}/events`;
}

export async function fetchWorkspaces() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/workspaces`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("workspace_request_failed");
    }
    const payload = await response.json();
    return payload.items || fallbackWorkspaces;
  } catch (_error) {
    return fallbackWorkspaces;
  }
}

export async function fetchRuns() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/runs`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("runs_request_failed");
    }
    const payload = await response.json();
    return payload.items || fallbackRuns;
  } catch (_error) {
    return fallbackRuns;
  }
}

export async function fetchRun(runId) {
  const runs = await fetchRuns();
  return runs.find((item) => item.id === runId) || null;
}

export async function fetchRunMemory(runId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/runs/${runId}/memory`, {
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error("run_memory_request_failed");
    }
    return await response.json();
  } catch (_error) {
    return {
      session_id: "session-sample",
      run_id: runId,
      total_turns: 2,
      summary: "用户要求中文输出，并关注 ERP 写入风险。",
      facts: [
        { key: "language", value: "zh-CN", source: "user" },
        { key: "risk_focus", value: "erp-write", source: "user" },
      ],
      recent_turns: [
        {
          id: "turn-sample-1",
          role: "user",
          content: "请用中文总结审批风险。",
          created_at: "2026-03-29T00:00:00Z",
        },
      ],
    };
  }
}

export async function uploadKnowledgeFile(formData, { signal, timeoutMs = 600000 } = {}) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/knowledge/uploads`, {
    method: "POST",
    body: formData,
    signal,
    timeoutMs,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "knowledge_upload_failed"));
  }

  return response.json();
}

export async function listKnowledgeUploads({ workspaceId, limit = 10, signal, timeoutMs = 30000 }) {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    limit: String(limit),
  });
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/knowledge/uploads?${params.toString()}`, {
    method: "GET",
    cache: "no-store",
    signal,
    timeoutMs,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "knowledge_uploads_request_failed"));
  }

  return response.json();
}

export async function searchKnowledge({ workspaceId, query, signal, timeoutMs = 30000 }) {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    query,
  });
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/knowledge/search?${params.toString()}`, {
    method: "GET",
    cache: "no-store",
    signal,
    timeoutMs,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "knowledge_search_failed"));
  }

  return response.json();
}

export async function fetchKnowledgeIndexStatus({ timeoutMs = 10000 } = {}) {
  try {
    const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/knowledge/index/status`, {
      method: "GET",
      cache: "no-store",
      timeoutMs,
    });

    if (!response.ok) {
      throw new Error("knowledge_index_status_failed");
    }

    return await response.json();
  } catch (_error) {
    return {
      backend_mode: "fallback",
      backend_reason: "status_unavailable",
      collection_name: "emata_documents",
      collection_ready: false,
      indexed_record_count: 0,
      endpoint: "",
    };
  }
}

export async function createAskSession({
  skillId = "hr_recruiting",
  title = "HR Recruiting Copilot",
  initialContext = {},
} = {}) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      skill_id: skillId,
      title,
      initial_context: initialContext,
    }),
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "ask_session_create_failed"));
  }

  return response.json();
}

export async function fetchAskSession(sessionId) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/sessions/${sessionId}`, {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "ask_session_request_failed"));
  }

  return response.json();
}

export async function fetchFeishuBindingStatus() {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/bindings/feishu/status`, {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "feishu_binding_status_failed"));
  }

  return response.json();
}

export async function startFeishuBinding({ timeoutMs = 30000, forceRebind = false } = {}) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/bindings/feishu/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force_rebind: forceRebind }),
    timeoutMs,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "feishu_binding_start_failed"));
  }

  return response.json();
}

export async function completeFeishuBinding({ deviceCode = "", timeoutMs = 30000 } = {}) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/bindings/feishu/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_code: deviceCode }),
    timeoutMs,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "feishu_binding_complete_failed"));
  }

  return response.json();
}

export async function disconnectFeishuBinding({ timeoutMs = 30000 } = {}) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/bindings/feishu/disconnect`, {
    method: "POST",
    timeoutMs,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "feishu_binding_disconnect_failed"));
  }

  return response.json();
}

export async function fetchAskTurns(sessionId) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/sessions/${sessionId}/turns`, {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "ask_turns_request_failed"));
  }

  return response.json();
}

export async function fetchAskArtifacts(sessionId) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/sessions/${sessionId}/artifacts`, {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "ask_artifacts_request_failed"));
  }

  return response.json();
}

export async function createAskTurn(sessionId, { content, signal, timeoutMs = ASK_TURN_TIMEOUT_MS }) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/sessions/${sessionId}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
    signal,
    timeoutMs,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "ask_turn_create_failed"));
  }

  return response.json();
}

export async function runAskCommand(
  sessionId,
  { command, payload = {}, signal, timeoutMs = ASK_COMMAND_TIMEOUT_MS },
) {
  const response = await fetchWithTimeout(`${API_BASE_URL}/api/v1/ask/sessions/${sessionId}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
    signal,
    timeoutMs,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "ask_command_failed"));
  }

  return response.json();
}

export async function fetchAskJobStatus(jobId) {
  const response = await fetchWithTimeout(buildAskJobStatusUrl(jobId), {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "ask_job_request_failed"));
  }

  return response.json();
}

export function subscribeAskJob(jobId, onMessage) {
  const source = new EventSource(buildAskJobEventsUrl(jobId));
  source.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch (_error) {
      // Ignore malformed events and keep the stream alive.
    }
  };
  source.onerror = () => {
    source.close();
  };
  return () => source.close();
}

async function readErrorMessage(response, fallback) {
  try {
    const payload = await response.json();
    if (typeof payload?.detail === "string") {
      return payload.detail;
    }
  } catch (_error) {
    return fallback;
  }
  return fallback;
}

async function fetchWithTimeout(url, { signal, timeoutMs = 30000, ...options } = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort("request_timeout"), timeoutMs);
  const abortExternal = () => controller.abort(signal?.reason || "request_canceled");

  if (signal) {
    if (signal.aborted) {
      abortExternal();
    } else {
      signal.addEventListener("abort", abortExternal, { once: true });
    }
  }

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      const reason = controller.signal.reason || "request_canceled";
      throw new Error(reason === "request_timeout" ? "request_timeout" : "request_canceled");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
    if (signal) {
      signal.removeEventListener("abort", abortExternal);
    }
  }
}
