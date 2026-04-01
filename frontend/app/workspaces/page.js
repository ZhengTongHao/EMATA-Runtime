import Link from "next/link";

import { fetchWorkspaces } from "../../lib/api";

export default async function WorkspacesPage() {
  const workspaces = await fetchWorkspaces();

  return (
    <main className="shell detail-shell">
      <div className="panel-header">
        <h1>Workspace 路由</h1>
        <Link href="/">返回控制台</Link>
      </div>
      <div className="grid">
        {workspaces.map((workspace) => (
          <section className="panel" key={workspace.id}>
            <h2>{workspace.name}</h2>
            <p className="subtitle">{workspace.description}</p>
            <ul>
              <li>ID: {workspace.id}</li>
              <li>Organization: {workspace.organization_id}</li>
              <li>Knowledge Scope: private + shared</li>
            </ul>
          </section>
        ))}
      </div>
    </main>
  );
}
