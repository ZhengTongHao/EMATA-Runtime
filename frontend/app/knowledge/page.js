import Link from "next/link";

import KnowledgeSearchPanel from "../../components/knowledge-search-panel";
import KnowledgeUploadForm from "../../components/knowledge-upload-form";
import { fetchKnowledgeIndexStatus, fetchWorkspaces } from "../../lib/api";
import { buildKnowledgeConsoleViewModel } from "../../lib/knowledge";

export default async function KnowledgePage({ workspaces: injectedWorkspaces } = {}) {
  const workspaces = injectedWorkspaces || (await fetchWorkspaces());
  const indexStatus = await fetchKnowledgeIndexStatus();
  const viewModel = buildKnowledgeConsoleViewModel({ workspaces, indexStatus });

  return (
    <main className="shell knowledge-shell">
      <section className="knowledge-hero">
        <div className="knowledge-hero-copy">
          <p className="eyebrow">KNOWLEDGE OPERATIONS</p>
          <h1>{viewModel.title}</h1>
          <p className="subtitle">{viewModel.subtitle}</p>
          <div className="hero-actions">
            <Link className="ghost-link" href="/">
              返回控制台
            </Link>
            <Link className="ghost-link" href="/workspaces">
              查看 Workspace
            </Link>
          </div>
        </div>

        <div className="knowledge-status-strip">
          <div className="status-tile">
            <span className="status-key">Upload</span>
            <strong className="status-value">DOCX / PPTX / XLSX / TXT</strong>
            <p>Office 文档和纯文本已经可以直接进入结构化 chunk 和检索链路。</p>
          </div>
          <div className="status-tile">
            <span className="status-key">PDF</span>
            <strong className="status-value">MinerU Required</strong>
            <p>PDF 走 MinerU CLI 解析；若运行环境未安装或超时，会在上传状态里明确给出失败原因。</p>
          </div>
          <div className="status-tile">
            <span className="status-key">Retrieve</span>
            <strong className="status-value">Chunk Trace</strong>
            <p>检索结果会展示 chunk 级定位元数据和 query rewrite 轨迹，方便调试召回质量。</p>
          </div>
          <div className="status-tile">
            <span className="status-key">{viewModel.indexStatus.key}</span>
            <strong className="status-value">{viewModel.indexStatus.value}</strong>
            <p>{viewModel.indexStatus.description}</p>
          </div>
        </div>
      </section>

      <section className="knowledge-grid">
        <KnowledgeUploadForm viewModel={viewModel} />
        <KnowledgeSearchPanel viewModel={viewModel} />
      </section>
    </main>
  );
}
