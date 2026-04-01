import Link from "next/link";

import AskChat from "../../components/ask-chat";
import { fetchWorkspaces } from "../../lib/api";
import { buildAskPageViewModel } from "../../lib/ask";

export default async function AskPage() {
  const workspaces = await fetchWorkspaces();
  const viewModel = buildAskPageViewModel({ workspaces });

  return (
    <main className="shell knowledge-shell">
      <section className="knowledge-hero">
        <div className="knowledge-hero-copy">
          <p className="eyebrow">ASK WORKBENCH</p>
          <h1>{viewModel.title}</h1>
          <p className="subtitle">{viewModel.subtitle}</p>
          <div className="hero-actions">
            <Link className="ghost-link" href="/">
              返回控制台
            </Link>
            <Link className="ghost-link" href="/knowledge">
              打开知识运营台
            </Link>
          </div>
        </div>

        <div className="knowledge-status-strip">
          <div className="status-tile">
            <span className="status-key">Skill</span>
            <strong className="status-value">HR Recruiting</strong>
            <p>先聚焦看简历、安排面试、反馈汇总和录用推进，底层保持可扩展的 Skill Runtime。</p>
          </div>
          <div className="status-tile">
            <span className="status-key">Runtime</span>
            <strong className="status-value">Session / Turn / Command</strong>
            <p>前端直接消费统一的 TurnResult，不再额外维护一套领域状态机。</p>
          </div>
          <div className="status-tile">
            <span className="status-key">Tools</span>
            <strong className="status-value">Controlled lark-cli</strong>
            <p>高风险内部协同先确认，确认后再走受控 tool 执行链路。</p>
          </div>
        </div>
      </section>

      <AskChat viewModel={viewModel} />
    </main>
  );
}
