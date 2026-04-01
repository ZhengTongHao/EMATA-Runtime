export function buildDashboardViewModel({ runs = [], workspaces = [] }) {
  const summary = {
    totalRuns: runs.length,
    pendingApprovals: runs.filter((item) => item.status === "WAITING_APPROVAL").length,
    failedRuns: runs.filter((item) => item.status === "FAILED").length,
  };

  const highlightRun =
    runs.find((item) => item.status === "WAITING_APPROVAL") ||
    runs.find((item) => item.status === "RUNNING") ||
    runs[0] ||
    null;

  return {
    summary,
    highlightRun,
    workspaceOptions: workspaces.map((item) => ({
      id: item.id,
      label: item.name,
    })),
  };
}
