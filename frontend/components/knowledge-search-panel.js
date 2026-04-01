"use client";

import { useDeferredValue, useEffect, useRef, useState } from "react";

import { searchKnowledge } from "../lib/api";
import {
  formatKnowledgeErrorMessage,
  formatSearchResultExplanation,
  formatSearchResultMeta,
  formatSearchTraceSummary,
  getSearchSubmitLabel,
} from "../lib/knowledge";

export default function KnowledgeSearchPanel({ viewModel }) {
  const [workspaceId, setWorkspaceId] = useState(viewModel.defaultWorkspaceId);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [trace, setTrace] = useState(null);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState("");
  const [isRequesting, setIsRequesting] = useState(false);
  const deferredQuery = useDeferredValue(query);
  const requestControllerRef = useRef(null);

  useEffect(() => {
    setResults([]);
    setTrace(null);
    setSearched(false);
    setError("");
  }, [workspaceId]);

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      setError("请先输入一个检索问题。");
      return;
    }

    const controller = new AbortController();
    requestControllerRef.current = controller;
    setError("");
    setIsRequesting(true);

    try {
      const payload = await searchKnowledge({
        workspaceId,
        query: trimmedQuery,
        signal: controller.signal,
        timeoutMs: viewModel.searchTimeoutMs,
      });
      setResults(payload.items || []);
      setTrace(payload.trace || null);
      setSearched(true);
    } catch (requestError) {
      if (requestError.message !== "request_canceled") {
        setResults([]);
        setTrace(null);
        setSearched(true);
      }
      setError(formatKnowledgeErrorMessage(requestError.message));
    } finally {
      requestControllerRef.current = null;
      setIsRequesting(false);
    }
  }

  function handleCancelSearch() {
    requestControllerRef.current?.abort("request_canceled");
  }

  return (
    <section className="panel knowledge-panel">
      <div className="panel-header knowledge-panel-header">
        <div>
          <p className="eyebrow">RETRIEVE</p>
          <h2>{viewModel.searchHeading}</h2>
        </div>
        <span className="badge badge-running">{results.length} Hits</span>
      </div>

      <p className="subtitle">{viewModel.searchHint}</p>

      <form className="knowledge-form" onSubmit={handleSubmit}>
        <div className="field-grid">
          <label className="field">
            <span>Workspace</span>
            <select
              value={workspaceId}
              onChange={(event) => setWorkspaceId(event.target.value)}
              disabled={isRequesting}
            >
              {viewModel.workspaceOptions.map((workspace) => (
                <option value={workspace.id} key={workspace.id}>
                  {workspace.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Query</span>
            <input
              type="text"
              placeholder="例如：报销审批、ERP 风险、discount battlecard"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              disabled={isRequesting}
            />
          </label>
        </div>

        <div className="sample-chip-row">
          {viewModel.sampleQueries.map((sample) => (
            <button
              type="button"
              className="sample-chip"
              key={sample}
              onClick={() => setQuery(sample)}
              disabled={isRequesting}
            >
              {sample}
            </button>
          ))}
        </div>

        <div className="action-row">
          <button className="action-button subtle" disabled={isRequesting} type="submit">
            {getSearchSubmitLabel({ isRequesting })}
          </button>
          {isRequesting ? (
            <button className="action-button ghost" type="button" onClick={handleCancelSearch}>
              取消检索
            </button>
          ) : null}
        </div>
      </form>

      {error ? (
        <div className="status-banner status-error">
          <strong>检索提示</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {trace ? (
        <div className="status-banner status-trace">
          <strong>检索轨迹</strong>
          <span>{formatSearchTraceSummary(trace)}</span>
          <div className="trace-chip-row">
            {trace.query_variants?.map((variant) => (
              <span className="sample-chip trace-chip" key={variant}>
                {variant}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="result-stack">
        {searched ? (
          results.length ? (
            results.map((item) => (
              <article className="result-item" key={item.chunk_id}>
                <div className="result-head">
                  <div>
                    <strong>{item.title}</strong>
                    <p className="meta-line">{formatSearchResultMeta(item) || item.scope}</p>
                  </div>
                  <span className="result-score">
                    {item.score == null ? "fallback" : item.score.toFixed(3)}
                  </span>
                </div>
                <p className="result-snippet">{item.snippet}</p>
                {formatSearchResultExplanation(item) ? (
                  <p className="meta-line">{formatSearchResultExplanation(item)}</p>
                ) : null}
              </article>
            ))
          ) : (
            <div className="status-banner status-idle">
              <strong>没有命中</strong>
              <span>当前 workspace 下没有命中，试试换一个 query 或切换 workspace。</span>
            </div>
          )
        ) : (
          <div className="status-banner status-idle">
            <strong>准备就绪</strong>
            <span>
              {deferredQuery
                ? `准备检索：${deferredQuery}`
                : "输入查询后，这里会展示 chunk 级命中、定位元数据和本次检索轨迹。"}
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
