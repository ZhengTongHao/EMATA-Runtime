import Link from "next/link";

import { fetchRuns, fetchWorkspaces } from "../lib/api";
import { buildDashboardViewModel } from "../lib/dashboard";

function SummaryCard({ label, value }) {
  return (
    <div className="summary-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export default async function HomePage() {
  const [runs, workspaces] = await Promise.all([fetchRuns(), fetchWorkspaces()]);
  const viewModel = buildDashboardViewModel({ runs, workspaces });

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">EMATA CONTROL PLANE</p>
          <h1>企业级多 Agent 任务中枢</h1>
          <p className="subtitle">
            统一查看 Run 状态、审批入口、Workspace 边界，以及知识库上传与 chunk 检索。
          </p>
          <div className="hero-actions">
            <Link className="ghost-link" href="/ask">
              进入 Ask 工作台
            </Link>
            <Link className="ghost-link" href="/knowledge">
              进入知识库操作台
            </Link>
            <Link className="ghost-link" href="/workspaces">
              查看 Workspace
            </Link>
          </div>
        </div>
        <div className="summary-grid">
          <SummaryCard label="总 Run 数" value={viewModel.summary.totalRuns} />
          <SummaryCard label="待审批" value={viewModel.summary.pendingApprovals} />
          <SummaryCard label="失败 Run" value={viewModel.summary.failedRuns} />
        </div>
      </section>

      <section className="grid">
        <div className="panel">
          <div className="panel-header">
            <h2>重点 Run</h2>
            <Link href="/knowledge">知识库操作台</Link>
          </div>
          {viewModel.highlightRun ? (
            <div className="run-card featured">
              <span className={`badge badge-${viewModel.highlightRun.status.toLowerCase()}`}>
                {viewModel.highlightRun.status}
              </span>
              <h3>{viewModel.highlightRun.title}</h3>
              <p>{viewModel.highlightRun.goal}</p>
              <Link href={`/runs/${viewModel.highlightRun.id}`}>打开详情</Link>
            </div>
          ) : (
            <p>当前没有 Run。</p>
          )}
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2>最近 Run</h2>
            <span>{runs.length} items</span>
          </div>
          <div className="run-list">
            {runs.map((item) => (
              <div className="run-card" key={item.id}>
                <div className="run-head">
                  <strong>{item.title}</strong>
                  <span className={`badge badge-${item.status.toLowerCase()}`}>{item.status}</span>
                </div>
                <p>{item.goal}</p>
                <div className="run-foot">
                  <span>{item.workspace_id}</span>
                  <Link href={`/runs/${item.id}`}>详情</Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
