import test from "node:test";
import assert from "node:assert/strict";

import { buildDashboardViewModel } from "../lib/dashboard.js";

test("buildDashboardViewModel exposes summary cards and pending approvals", () => {
  const viewModel = buildDashboardViewModel({
    runs: [
      { id: "run-1", status: "WAITING_APPROVAL", title: "ERP sync" },
      { id: "run-2", status: "RUNNING", title: "Generate report" },
      { id: "run-3", status: "FAILED", title: "CRM writeback" },
    ],
    workspaces: [
      { id: "workspace-finance", name: "Finance" },
      { id: "workspace-sales", name: "Sales" },
    ],
  });

  assert.equal(viewModel.summary.totalRuns, 3);
  assert.equal(viewModel.summary.pendingApprovals, 1);
  assert.equal(viewModel.summary.failedRuns, 1);
  assert.equal(viewModel.workspaceOptions.length, 2);
  assert.equal(viewModel.highlightRun.id, "run-1");
});
