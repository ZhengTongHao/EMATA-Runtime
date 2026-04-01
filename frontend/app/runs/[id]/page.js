import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchRun, fetchRunMemory } from "../../../lib/api";

export default async function RunDetailPage({ params }) {
  const [run, memory] = await Promise.all([fetchRun(params.id), fetchRunMemory(params.id)]);
  if (!run) {
    notFound();
  }

  return (
    <main className="shell detail-shell">
      <Link href="/">返回控制台</Link>
      <section className="panel">
        <span className={`badge badge-${run.status.toLowerCase()}`}>{run.status}</span>
        <h1>{run.title}</h1>
        <p className="subtitle">{run.goal}</p>
        <div className="detail-grid">
          <div>
            <h2>执行上下文</h2>
            <ul>
              <li>Workspace: {run.workspace_id}</li>
              <li>Capability: {run.requested_capability}</li>
              <li>Run ID: {run.id}</li>
            </ul>
          </div>
          <div>
            <h2>审批建议</h2>
            <p>
              高风险写操作默认要求人工审批。飞书只作为提醒与跳转入口，最终审批真相仍落在
              EMATA 控制台。
            </p>
          </div>
          <div>
            <h2>短期记忆</h2>
            <p>{memory.summary || "当前还没有压缩摘要。"}</p>
            <ul>
              {memory.facts.map((fact) => (
                <li key={`${fact.key}-${fact.value}`}>
                  {fact.key}: {fact.value}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
    </main>
  );
}
