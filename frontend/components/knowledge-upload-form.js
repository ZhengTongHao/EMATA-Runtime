"use client";

import { useEffect, useRef, useState } from "react";

import { listKnowledgeUploads, uploadKnowledgeFile } from "../lib/api";
import {
  formatKnowledgeErrorMessage,
  formatUploadFailureReason,
  formatUploadHistoryMeta,
  formatUploadHistorySummary,
  getUploadSubmitLabel,
} from "../lib/knowledge";

export default function KnowledgeUploadForm({ viewModel }) {
  const [workspaceId, setWorkspaceId] = useState(viewModel.defaultWorkspaceId);
  const [scope, setScope] = useState("workspace");
  const [selectedFileName, setSelectedFileName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const uploadControllerRef = useRef(null);
  const historyRequestIdRef = useRef(0);
  const historyRefreshTimerRef = useRef(null);
  const workspaceIdRef = useRef(workspaceId);

  useEffect(() => {
    workspaceIdRef.current = workspaceId;
    setResult(null);
    setError("");
    setHistory([]);
    setHistoryError("");
    setSelectedFileName("");
  }, [workspaceId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadHistory({ workspaceId: workspaceIdRef.current, signal: controller.signal });
    return () => {
      controller.abort("request_canceled");
      if (historyRefreshTimerRef.current) {
        clearTimeout(historyRefreshTimerRef.current);
      }
    };
  }, [workspaceId]);

  async function loadHistory({ workspaceId: targetWorkspaceId, signal } = {}) {
    const requestedWorkspaceId = targetWorkspaceId || workspaceIdRef.current;
    const requestId = historyRequestIdRef.current + 1;
    historyRequestIdRef.current = requestId;
    setIsHistoryLoading(true);
    setHistoryError("");

    try {
      const payload = await listKnowledgeUploads({
        workspaceId: requestedWorkspaceId,
        limit: 8,
        signal,
      });
      if (
        requestId !== historyRequestIdRef.current ||
        requestedWorkspaceId !== workspaceIdRef.current
      ) {
        return;
      }
      setHistory(payload.items || []);
    } catch (requestError) {
      if (requestError.message === "request_canceled") {
        return;
      }
      if (
        requestId !== historyRequestIdRef.current ||
        requestedWorkspaceId !== workspaceIdRef.current
      ) {
        return;
      }
      setHistoryError(formatKnowledgeErrorMessage(requestError.message));
    } finally {
      if (requestId === historyRequestIdRef.current) {
        setIsHistoryLoading(false);
      }
    }
  }

  function scheduleHistoryRefresh(delayMs = 0, targetWorkspaceId = workspaceIdRef.current) {
    if (historyRefreshTimerRef.current) {
      clearTimeout(historyRefreshTimerRef.current);
    }
    historyRefreshTimerRef.current = setTimeout(() => {
      void loadHistory({ workspaceId: targetWorkspaceId });
    }, delayMs);
  }

  async function refreshHistoryNow(targetWorkspaceId) {
    await loadHistory({ workspaceId: targetWorkspaceId });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const fileField = form.elements.namedItem("file");
    const file = fileField?.files?.[0];

    if (!file) {
      setError("请先选择一个文件。");
      return;
    }

    const submittedWorkspaceId = workspaceIdRef.current;
    const submittedScope = scope;
    const formData = new FormData();
    formData.set("workspace_id", submittedWorkspaceId);
    formData.set("scope", submittedScope);
    formData.set("file", file);

    const controller = new AbortController();
    uploadControllerRef.current = controller;
    setIsSubmitting(true);
    setError("");

    try {
      const payload = await uploadKnowledgeFile(formData, {
        signal: controller.signal,
        timeoutMs: viewModel.uploadTimeoutMs,
      });
      setResult(payload);
      scheduleHistoryRefresh(0, submittedWorkspaceId);
    } catch (requestError) {
      setResult(null);
      setError(formatKnowledgeErrorMessage(requestError.message));
      if (requestError.message === "request_canceled" || requestError.message === "request_timeout") {
        await refreshHistoryNow(submittedWorkspaceId);
        scheduleHistoryRefresh(1800, submittedWorkspaceId);
      } else {
        scheduleHistoryRefresh(0, submittedWorkspaceId);
      }
    } finally {
      uploadControllerRef.current = null;
      setIsSubmitting(false);
    }
  }

  function handleCancelUpload() {
    uploadControllerRef.current?.abort("request_canceled");
  }

  return (
    <section className="panel knowledge-panel">
      <div className="panel-header knowledge-panel-header">
        <div>
          <p className="eyebrow">INGEST</p>
          <h2>{viewModel.uploadHeading}</h2>
        </div>
        <span className="badge badge-running">MULTI FORMAT</span>
      </div>

      <p className="subtitle">{viewModel.uploadHint}</p>

      <div className="support-chip-row">
        {viewModel.supportedFormats.map((format) => (
          <span className="sample-chip support-chip" key={format}>
            {format}
          </span>
        ))}
      </div>

      <div className="support-list">
        {viewModel.parserRoutes.map((route) => (
          <div className="support-row" key={route.label}>
            <strong>{route.label}</strong>
            <span>{route.detail}</span>
          </div>
        ))}
      </div>

      <form className="knowledge-form" onSubmit={handleSubmit}>
        <div className="field-grid">
          <label className="field">
            <span>Workspace</span>
            <select
              value={workspaceId}
              onChange={(event) => setWorkspaceId(event.target.value)}
              disabled={isSubmitting}
            >
              {viewModel.workspaceOptions.map((workspace) => (
                <option value={workspace.id} key={workspace.id}>
                  {workspace.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Scope</span>
            <select
              value={scope}
              onChange={(event) => setScope(event.target.value)}
              disabled={isSubmitting}
            >
              <option value="workspace">Workspace Private</option>
              <option value="shared">Organization Shared</option>
            </select>
          </label>
        </div>

        <label className="upload-dropzone">
          <span className="field-label">Source File</span>
          <strong>{selectedFileName || "选择一个文件开始上传"}</strong>
          <span className="upload-note">
            TXT、DOCX、PPTX、XLSX 会直接进入结构化切分；PDF 需要运行环境可用的 MinerU CLI。
          </span>
          <input
            name="file"
            type="file"
            accept={viewModel.fileAccept}
            disabled={isSubmitting}
            onChange={(event) => setSelectedFileName(event.target.files?.[0]?.name || "")}
          />
        </label>

        <div className="action-row">
          <button className="action-button" disabled={isSubmitting} type="submit">
            {getUploadSubmitLabel({ isSubmitting })}
          </button>
          {isSubmitting ? (
            <button className="action-button ghost" type="button" onClick={handleCancelUpload}>
              停止等待
            </button>
          ) : null}
        </div>
      </form>

      {error ? (
        <div className="status-banner status-error">
          <strong>上传提示</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {result ? (
        <div className="status-banner status-success">
          <strong>{result.status}</strong>
          <span>{result.filename}</span>
          <span>{formatUploadHistoryMeta(result)}</span>
          {result.ingestion_summary ? (
            <span>{formatUploadHistorySummary(result)}</span>
          ) : null}
          <span className="status-path">{result.storage_path}</span>
        </div>
      ) : (
        <div className="status-banner status-idle">
          <strong>准备就绪</strong>
          <span>上传完成后，这里会显示解析状态、chunk 数量和对象存储路径。</span>
        </div>
      )}

      <section className="upload-history">
        <div className="panel-header knowledge-panel-header">
          <div>
            <p className="eyebrow">RECENT</p>
            <h3>{viewModel.uploadHistoryHeading}</h3>
          </div>
          <span className="badge badge-running">{history.length} Items</span>
        </div>
        <p className="subtitle">{viewModel.uploadHistoryHint}</p>

        {historyError ? (
          <div className="status-banner status-error">
            <strong>历史加载失败</strong>
            <span>{historyError}</span>
          </div>
        ) : null}

        {isHistoryLoading ? (
          <div className="status-banner status-idle">
            <strong>正在加载</strong>
            <span>正在刷新最近上传记录。</span>
          </div>
        ) : history.length ? (
          <div className="result-stack">
            {history.map((item) => (
              <article className="history-item" key={item.id}>
                <div className="result-head">
                  <div>
                    <strong>{item.filename}</strong>
                    <p className="meta-line">{formatUploadHistoryMeta(item)}</p>
                    {item.ingestion_summary ? (
                      <p className="meta-line">{formatUploadHistorySummary(item)}</p>
                    ) : null}
                  </div>
                  <span className={`badge badge-${item.status.toLowerCase()}`}>{item.status}</span>
                </div>
                {item.error_message || item.error_code ? (
                  <p className="result-snippet">
                    {formatUploadFailureReason(item)}
                  </p>
                ) : (
                  <p className="result-snippet">{item.storage_path}</p>
                )}
              </article>
            ))}
          </div>
        ) : (
          <div className="status-banner status-idle">
            <strong>还没有上传记录</strong>
            <span>先上传一份文档，这里就会累积最近的解析结果和失败原因。</span>
          </div>
        )}
      </section>
    </section>
  );
}
