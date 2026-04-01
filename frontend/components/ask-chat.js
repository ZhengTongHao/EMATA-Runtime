"use client";

import { useEffect, useRef, useState } from "react";

import {
  completeFeishuBinding,
  createAskSession,
  createAskTurn,
  disconnectFeishuBinding,
  fetchAskJobStatus,
  fetchAskArtifacts,
  fetchAskSession,
  fetchAskTurns,
  fetchFeishuBindingStatus,
  runAskCommand,
  startFeishuBinding,
  subscribeAskJob,
} from "../lib/api";
import {
  buildActionPreviewModel,
  buildTargetSelectionModel,
  formatAskErrorMessage,
  formatAskJobStatus,
  formatAskOutputLabel,
  formatFeishuBindingHint,
  formatFeishuBindingStatus,
  partitionTurnOutputs,
  formatToolResultError,
  formatToolResultSummary,
} from "../lib/ask";

function mergeSessionWithBinding(session, binding) {
  if (!session) {
    return session;
  }
  return {
    ...session,
    feishu_binding_status: binding?.status || "UNBOUND",
    feishu_identity: binding?.identity || {},
    required_scopes: binding?.required_scopes || [],
    missing_scopes: binding?.missing_scopes || [],
  };
}

function shouldRenderInputBubble(turn) {
  return turn?.input_type !== "command";
}

function collectJobIdsFromTurns(turnItems = []) {
  const jobIds = new Set();
  for (const turn of turnItems) {
    for (const output of turn?.outputs || []) {
      const jobId = output?.data?.job_id;
      if (jobId) {
        jobIds.add(jobId);
      }
    }
  }
  return [...jobIds];
}

export default function AskChat({ viewModel }) {
  const [session, setSession] = useState(null);
  const [binding, setBinding] = useState(null);
  const [turns, setTurns] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [input, setInput] = useState("");
  const [draftEdits, setDraftEdits] = useState({});
  const [jobStates, setJobStates] = useState({});
  const [error, setError] = useState("");
  const [isBusy, setIsBusy] = useState(true);
  const requestControllerRef = useRef(null);
  const jobUnsubscribersRef = useRef({});
  const jobPollTimersRef = useRef({});

  function updateBindingState(payload) {
    setBinding(payload);
    setSession((current) => mergeSessionWithBinding(current, payload));
  }

  function mergeJobState(payload) {
    if (!payload?.id) {
      return;
    }
    setJobStates((current) => ({
      ...current,
      [payload.id]: payload,
    }));
  }

  function stopTrackingJob(jobId) {
    if (!jobId) {
      return;
    }
    const unsubscribe = jobUnsubscribersRef.current[jobId];
    if (unsubscribe) {
      unsubscribe();
      delete jobUnsubscribersRef.current[jobId];
    }
    const timer = jobPollTimersRef.current[jobId];
    if (timer) {
      window.clearTimeout(timer);
      delete jobPollTimersRef.current[jobId];
    }
  }

  function clearJobPoll(jobId) {
    const timer = jobPollTimersRef.current[jobId];
    if (timer) {
      window.clearTimeout(timer);
      delete jobPollTimersRef.current[jobId];
    }
  }

  function scheduleJobPoll(jobId, delayMs = 1200) {
    clearJobPoll(jobId);
    jobPollTimersRef.current[jobId] = window.setTimeout(async () => {
      try {
        const payload = await fetchAskJobStatus(jobId);
        mergeJobState(payload);
        if (!["finished", "failed"].includes(payload.status)) {
          scheduleJobPoll(jobId, 1200);
        } else {
          stopTrackingJob(jobId);
        }
      } catch (_error) {
        stopTrackingJob(jobId);
      }
    }, delayMs);
  }

  function trackJob(jobId) {
    if (!jobId || jobUnsubscribersRef.current[jobId]) {
      return;
    }

    fetchAskJobStatus(jobId)
      .then((payload) => {
        mergeJobState(payload);
        if (!["finished", "failed"].includes(payload.status)) {
          scheduleJobPoll(jobId);
        }
      })
      .catch(() => {
        scheduleJobPoll(jobId, 800);
      });

    if (typeof window !== "undefined" && typeof window.EventSource === "function") {
      const unsubscribe = subscribeAskJob(jobId, (payload) => {
        mergeJobState(payload);
        if (["finished", "failed"].includes(payload.status)) {
          stopTrackingJob(jobId);
        }
      });
      jobUnsubscribersRef.current[jobId] = unsubscribe;
    }
  }

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      try {
        const created = await createAskSession({
          skillId: viewModel.defaultSkillId,
          title: viewModel.defaultTitle,
        });
        const [bindingPayload, history, artifactPayload] = await Promise.all([
          fetchFeishuBindingStatus(),
          fetchAskTurns(created.id),
          fetchAskArtifacts(created.id),
        ]);
        if (!active) {
          return;
        }
        updateBindingState(bindingPayload);
        setSession((current) => mergeSessionWithBinding(created, bindingPayload));
        setTurns(history.items || []);
        setArtifacts(artifactPayload.items || []);
        collectJobIdsFromTurns(history.items || []).forEach(trackJob);
      } catch (requestError) {
        if (!active) {
          return;
        }
        setError(formatAskErrorMessage(requestError.message));
      } finally {
        if (active) {
          setIsBusy(false);
        }
      }
    }

    bootstrap();
    return () => {
      active = false;
      requestControllerRef.current?.abort("request_canceled");
      Object.keys(jobUnsubscribersRef.current).forEach((jobId) => stopTrackingJob(jobId));
    };
  }, [viewModel.defaultSkillId, viewModel.defaultTitle]);

  async function refreshArtifacts(sessionId) {
    const artifactPayload = await fetchAskArtifacts(sessionId);
    setArtifacts(artifactPayload.items || []);
  }

  async function resyncSession(sessionId) {
    const [sessionPayload, turnsPayload, artifactPayload, bindingPayload] = await Promise.all([
      fetchAskSession(sessionId),
      fetchAskTurns(sessionId),
      fetchAskArtifacts(sessionId),
      fetchFeishuBindingStatus(),
    ]);
    updateBindingState(bindingPayload);
    setSession(mergeSessionWithBinding(sessionPayload, bindingPayload));
    setTurns(turnsPayload.items || []);
    setArtifacts(artifactPayload.items || []);
    collectJobIdsFromTurns(turnsPayload.items || []).forEach(trackJob);
  }

  async function refreshBinding() {
    const payload = await fetchFeishuBindingStatus();
    updateBindingState(payload);
    return payload;
  }

  useEffect(() => {
    if (!binding?.device_code || binding.status !== "PENDING") {
      return undefined;
    }

    let active = true;
    let running = false;

    async function pollBinding() {
      if (!active || running) {
        return;
      }
      running = true;
      try {
        const payload = await completeFeishuBinding({
          deviceCode: binding.device_code,
          timeoutMs: 15000,
        });
        if (active) {
          updateBindingState(payload);
        }
      } catch (_error) {
        if (!active) {
          return;
        }
        try {
          const payload = await fetchFeishuBindingStatus();
          if (active) {
            updateBindingState(payload);
          }
        } catch (_refreshError) {
          // Keep the current pending state and try again on the next tick.
        }
      } finally {
        running = false;
      }
    }

    pollBinding();
    const timer = window.setInterval(pollBinding, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [binding?.device_code, binding?.status]);

  function applyTurnResult(payload) {
    setTurns((current) => [...current, payload.turn]);
    setSession((current) =>
      current
        ? mergeSessionWithBinding(
            {
              ...current,
              active_context: { ...(current.active_context || {}), ...(payload.state_patch || {}) },
            },
            binding,
          )
        : current,
    );
    collectJobIdsFromTurns([payload.turn]).forEach(trackJob);
  }

  function updateDraftEdit(turnId, field, value) {
    setDraftEdits((current) => ({
      ...current,
      [turnId]: {
        ...(current[turnId] || {}),
        [field]: value,
      },
    }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const content = input.trim();
    if (!content || !session) {
      return;
    }

    const controller = new AbortController();
    requestControllerRef.current = controller;
    setIsBusy(true);
    setError("");
    setInput("");

    try {
      const payload = await createAskTurn(session.id, {
        content,
        signal: controller.signal,
      });
      applyTurnResult(payload);
      await refreshArtifacts(session.id);
      await refreshBinding();
    } catch (requestError) {
      if (requestError.message === "request_timeout" && session?.id) {
        try {
          await resyncSession(session.id);
          setError("请求超时，已自动刷新会话状态。");
          return;
        } catch (_refreshError) {
          // Fall through to the standard error path.
        }
      }
      setError(formatAskErrorMessage(requestError.message));
      setInput(content);
    } finally {
      requestControllerRef.current = null;
      setIsBusy(false);
    }
  }

  async function handleCommand(command) {
    if (!session) {
      return;
    }

    const controller = new AbortController();
    requestControllerRef.current = controller;
    setIsBusy(true);
    setError("");

    try {
      const payload = await runAskCommand(session.id, {
        command: command.type,
        payload: command.payload || {},
        signal: controller.signal,
      });
      applyTurnResult(payload);
      await refreshArtifacts(session.id);
      await refreshBinding();
    } catch (requestError) {
      if (requestError.message === "request_timeout" && session?.id) {
        try {
          await resyncSession(session.id);
          setError("请求超时，已自动刷新会话状态。");
          return;
        } catch (_refreshError) {
          // Fall through to the standard error path.
        }
      }
      setError(formatAskErrorMessage(requestError.message));
    } finally {
      requestControllerRef.current = null;
      setIsBusy(false);
    }
  }

  async function handleStartBinding({ forceRebind = false } = {}) {
    setIsBusy(true);
    setError("");
    try {
      const payload = await startFeishuBinding({ forceRebind });
      updateBindingState(payload);
      if (payload.verification_url) {
        window.open(payload.verification_url, "_blank", "noopener,noreferrer");
      }
    } catch (requestError) {
      setError(formatAskErrorMessage(requestError.message));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCompleteBinding() {
    setIsBusy(true);
    setError("");
    try {
      const payload = await completeFeishuBinding({
        deviceCode: binding?.device_code || "",
      });
      updateBindingState(payload);
    } catch (requestError) {
      setError(formatAskErrorMessage(requestError.message));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDisconnectBinding() {
    setIsBusy(true);
    setError("");
    try {
      const payload = await disconnectFeishuBinding();
      updateBindingState(payload);
    } catch (requestError) {
      setError(formatAskErrorMessage(requestError.message));
    } finally {
      setIsBusy(false);
    }
  }

  const missingScopes = binding?.missing_scopes || [];
  const bindingReady = binding?.status === "ACTIVE" && !missingScopes.length;

  return (
    <section className="ask-layout">
      <div className="panel ask-chat-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">ASK</p>
            <h2>{viewModel.title}</h2>
          </div>
          <span className="badge badge-running">{session ? "Session Ready" : "Booting"}</span>
        </div>

        <p className="subtitle">{viewModel.subtitle}</p>

        <div className={`status-banner ${bindingReady ? "status-idle" : "status-error"}`}>
          <strong>飞书状态：{formatFeishuBindingStatus(binding)}</strong>
          <span>{formatFeishuBindingHint(binding)}</span>
          <div className="action-row">
            {binding?.status !== "PENDING" ? (
              <button
                type="button"
                className="action-button subtle"
                onClick={() => handleStartBinding({ forceRebind: binding?.status === "REAUTH_REQUIRED" })}
                disabled={isBusy}
              >
                {bindingReady
                  ? "刷新飞书状态"
                  : binding?.status === "REAUTH_REQUIRED"
                    ? "重新授权飞书"
                    : "绑定飞书"}
              </button>
            ) : null}
            {binding?.status === "PENDING" && binding?.verification_url ? (
              <button
                type="button"
                className="action-button ghost"
                onClick={() => window.open(binding.verification_url, "_blank", "noopener,noreferrer")}
                disabled={isBusy}
              >
                打开授权页
              </button>
            ) : null}
            {binding?.status === "PENDING" ? (
              <button
                type="button"
                className="action-button subtle"
                onClick={refreshBinding}
                disabled={isBusy}
              >
                刷新绑定状态
              </button>
            ) : null}
            {binding?.status === "PENDING" ? (
              <button
                type="button"
                className="action-button ghost"
                onClick={handleCompleteBinding}
                disabled={isBusy}
              >
                立即检查是否已完成授权
              </button>
            ) : null}
            {binding?.status === "ACTIVE" ? (
              <button
                type="button"
                className="action-button subtle"
                onClick={() => handleStartBinding({ forceRebind: true })}
                disabled={isBusy}
              >
                更换账号
              </button>
            ) : null}
            {binding?.status === "REAUTH_REQUIRED" ? (
              <button
                type="button"
                className="action-button subtle"
                onClick={() => handleStartBinding({ forceRebind: true })}
                disabled={isBusy}
              >
                更换账号
              </button>
            ) : null}
            {binding?.status === "ACTIVE" || binding?.status === "REAUTH_REQUIRED" ? (
              <button
                type="button"
                className="action-button ghost"
                onClick={handleDisconnectBinding}
                disabled={isBusy}
              >
                退出授权
              </button>
            ) : null}
          </div>
        </div>

        {error ? (
          <div className="status-banner status-error">
            <strong>Ask 提示</strong>
            <span>{error}</span>
          </div>
        ) : null}

        <div className="ask-thread">
          {turns.length ? (
            turns.map((turn) => (
              <article className="ask-turn" key={turn.id}>
                {(() => {
                  const { primaryOutputs, citationOutputs } = partitionTurnOutputs(turn.outputs || []);
                  const previewOutput = primaryOutputs.find(
                    (output) => output.type === "card" && output?.data?.card_type === "action_preview",
                  );
                  const previewModel = previewOutput ? buildActionPreviewModel(previewOutput) : null;
                  const draftEdit = previewModel
                    ? {
                        summary: draftEdits[turn.id]?.summary ?? previewModel.summary,
                        text: draftEdits[turn.id]?.text ?? previewModel.text,
                      }
                    : null;
                  return (
                    <>
                {shouldRenderInputBubble(turn) ? (
                  <div className="ask-user-bubble">
                    <span className="field-label">User</span>
                    <p>{turn.content}</p>
                  </div>
                ) : null}

                <div className="ask-output-stack">
                  {primaryOutputs.map((output, index) => (
                    <div className={`ask-output ask-output-${output.type}`} key={`${turn.id}-${index}`}>
                      <span className="field-label">{formatAskOutputLabel(output.type)}</span>
                      <p>{output.text}</p>
                      {output.type === "card" && output?.data?.card_type === "confirmation_request" && output?.data?.actions?.length ? (
                        <div className="support-list">
                          {output.data.actions.map((action, actionIndex) => (
                            <div className="support-row" key={`${turn.id}-action-${actionIndex}`}>
                              <strong>{action.capability}</strong>
                              <span>{action.summary}</span>
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {output.type === "card" && output?.data?.card_type === "target_selection" ? (() => {
                        const targetSelection = buildTargetSelectionModel(output);
                        const clickableOptions = targetSelection.options.filter((option) => option.kind !== "other");
                        return (
                          <div className="support-list">
                            <div className="support-row">
                              <strong>联系人搜索结果</strong>
                              <span>{targetSelection.contacts.length ? `共 ${targetSelection.contacts.length} 条` : "无命中"}</span>
                            </div>
                            {targetSelection.contacts.length ? (
                              targetSelection.contacts.map((option, optionIndex) => (
                                <button
                                  type="button"
                                  className="action-button subtle"
                                  key={`${turn.id}-contact-${option.value || optionIndex}`}
                                  disabled={isBusy}
                                  onClick={() =>
                                    handleCommand({
                                      id: `select-contact-${optionIndex}`,
                                      type: "select_option",
                                      payload: option,
                                    })
                                  }
                                >
                                  {option.label}
                                </button>
                              ))
                            ) : (
                              <p className="meta-line">当前联系人搜索没有返回结果。</p>
                            )}
                            <div className="support-row">
                              <strong>会话搜索结果</strong>
                              <span>{targetSelection.chats.length ? `共 ${targetSelection.chats.length} 条` : "无命中"}</span>
                            </div>
                            {targetSelection.chats.length ? (
                              targetSelection.chats.map((option, optionIndex) => (
                                <button
                                  type="button"
                                  className="action-button subtle"
                                  key={`${turn.id}-chat-${option.value || optionIndex}`}
                                  disabled={isBusy}
                                  onClick={() =>
                                    handleCommand({
                                      id: `select-chat-${optionIndex}`,
                                      type: "select_option",
                                      payload: option,
                                    })
                                  }
                                >
                                  {option.label}
                                </button>
                              ))
                            ) : (
                              <p className="meta-line">当前会话搜索没有返回结果。</p>
                            )}
                            {targetSelection.otherOption ? (
                              <button
                                type="button"
                                className="action-button ghost"
                                disabled={isBusy}
                                onClick={() =>
                                  handleCommand({
                                    id: `${turn.id}-target-other`,
                                    type: "select_option",
                                    payload: targetSelection.otherOption,
                                  })
                                }
                              >
                                {targetSelection.otherOption.label}
                              </button>
                            ) : null}
                            <button
                              type="button"
                              className="action-button ghost"
                              disabled={isBusy}
                              onClick={() =>
                                handleCommand({
                                  id: `${turn.id}-cancel-target-selection`,
                                  type: "cancel",
                                  payload: {},
                                })
                              }
                            >
                              取消
                            </button>
                          </div>
                        );
                      })() : null}
                      {output.type === "card" && output?.data?.card_type === "clarification" ? (
                        <div className="support-list">
                          <button
                            type="button"
                            className="action-button ghost"
                            disabled={isBusy}
                            onClick={() =>
                              handleCommand({
                                id: `${turn.id}-cancel-clarification`,
                                type: "cancel",
                                payload: {},
                              })
                            }
                          >
                            取消
                          </button>
                        </div>
                      ) : null}
                      {output.type === "card" && output?.data?.card_type === "action_preview" && previewModel ? (
                        <div className="support-list">
                          <div className="support-row">
                            <strong>目标</strong>
                            <span>{previewModel.targetLabel || "待确认"}</span>
                          </div>
                          {previewModel.actions.map((action, actionIndex) => (
                            <div className="support-row" key={`${turn.id}-preview-action-${actionIndex}`}>
                              <strong>{action.capability}</strong>
                              <span>{action.summary}</span>
                            </div>
                          ))}
                          <label className="field">
                            <span>执行摘要</span>
                            <input
                              className="ask-input"
                              type="text"
                              value={draftEdit?.summary || ""}
                              onChange={(event) => updateDraftEdit(turn.id, "summary", event.target.value)}
                              disabled={isBusy}
                            />
                          </label>
                          <label className="field">
                            <span>发送内容</span>
                            <textarea
                              className="ask-textarea"
                              rows={3}
                              value={draftEdit?.text || ""}
                              onChange={(event) => updateDraftEdit(turn.id, "text", event.target.value)}
                              disabled={isBusy}
                            />
                          </label>
                          <p className="meta-line">
                            可编辑字段：{(previewModel.editableFields || []).join(" / ") || "无"}
                          </p>
                        </div>
                      ) : null}
                      {output.type === "message" && output?.data?.job_id ? (
                        <div className="support-list">
                          <div className="support-row">
                            <strong>后台任务</strong>
                            <span>{formatAskJobStatus(jobStates[output.data.job_id]?.status || output.data.job_status)}</span>
                          </div>
                          <div className="support-row">
                            <strong>任务类型</strong>
                            <span>{output.data.job_type || "message.send"}</span>
                          </div>
                          <div className="support-row">
                            <strong>任务摘要</strong>
                            <span>{output.data.job_summary || "执行动作"}</span>
                          </div>
                          {(jobStates[output.data.job_id]?.outputs || []).map((jobOutput, jobIndex) => (
                            <div className={`ask-output ask-output-${jobOutput.type}`} key={`${turn.id}-job-${jobIndex}`}>
                              <span className="field-label">{formatAskOutputLabel(jobOutput.type)}</span>
                              <p>{jobOutput.text}</p>
                              {jobOutput.type === "tool_result" ? (
                                <>
                                  <p className="meta-line">{formatToolResultSummary(jobOutput)}</p>
                                  {formatToolResultError(jobOutput) ? (
                                    <p className="meta-line">{formatToolResultError(jobOutput)}</p>
                                  ) : null}
                                </>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {output.type === "tool_result" ? (
                        <>
                          <p className="meta-line">{formatToolResultSummary(output)}</p>
                          {formatToolResultError(output) ? (
                            <p className="meta-line">{formatToolResultError(output)}</p>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                  ))}
                  {citationOutputs.length ? (
                    <details className="ask-output ask-output-citation-group">
                      <summary>{`查看引用（${citationOutputs.length}）`}</summary>
                      <div className="ask-output-stack">
                        {citationOutputs.map((output, index) => (
                          <div className="ask-output ask-output-citation" key={`${turn.id}-citation-${index}`}>
                            <span className="field-label">{formatAskOutputLabel(output.type)}</span>
                            <p>{output.text}</p>
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}
                </div>

                {turn.pending_commands?.length ? (
                  <div className="action-row">
                    {turn.pending_commands.map((command) => (
                      <button
                        type="button"
                        className={`action-button ${command.type === "cancel" ? "ghost" : "subtle"}`}
                        key={command.id || `${turn.id}-${command.type}`}
                        disabled={isBusy}
                        onClick={() =>
                          handleCommand(
                            previewModel && ["approve_plan", "confirm"].includes(command.type)
                              ? {
                                  ...command,
                                  payload: {
                                    ...(command.payload || {}),
                                    draft_updates: draftEdit || {},
                                  },
                                }
                              : command,
                          )
                        }
                      >
                        {command.title || command.type}
                      </button>
                    ))}
                  </div>
                ) : null}
                    </>
                  );
                })()}
              </article>
            ))
          ) : (
            <div className="status-banner status-idle">
              <strong>准备开始</strong>
              <span>{viewModel.emptyState}</span>
            </div>
          )}
        </div>

        <form className="knowledge-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>Message</span>
            <textarea
              className="ask-textarea"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="例如：帮我看简历"
              disabled={!session || isBusy}
              rows={4}
            />
          </label>

          <div className="action-row">
            <button className="action-button subtle" type="submit" disabled={!session || isBusy}>
              {isBusy ? "处理中..." : "发送到 Ask"}
            </button>
          </div>
        </form>
      </div>

      <aside className="panel ask-side-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">SESSION</p>
            <h2>当前上下文</h2>
          </div>
        </div>

        <div className="support-list">
          <div className="support-row">
            <strong>Skill</strong>
            <span>{session?.skill_id || viewModel.defaultSkillId}</span>
          </div>
          <div className="support-row">
            <strong>Workspace Scope</strong>
            <span>{viewModel.workspaceLabels.join(" / ") || "All Accessible Workspaces"}</span>
          </div>
          <div className="support-row">
            <strong>Position</strong>
            <span>{session?.active_context?.active_position || "未设置"}</span>
          </div>
          <div className="support-row">
            <strong>Skill State</strong>
            <span>{session?.active_context?.active_skill_state || "idle"}</span>
          </div>
          <div className="support-row">
            <strong>Feishu</strong>
            <span>{formatFeishuBindingStatus(binding)}</span>
          </div>
        </div>

        <div className="ask-artifact-stack">
          <div className="panel-header">
            <h3>最近产物</h3>
            <span>{artifacts.length}</span>
          </div>
          {artifacts.length ? (
            artifacts.map((artifact) => (
              <article className="result-item" key={artifact.id}>
                <strong>{artifact.title}</strong>
                <p className="meta-line">{artifact.artifact_type}</p>
              </article>
            ))
          ) : (
            <p className="meta-line">当前还没有生成新的文档或分析产物。</p>
          )}
        </div>
      </aside>
    </section>
  );
}
