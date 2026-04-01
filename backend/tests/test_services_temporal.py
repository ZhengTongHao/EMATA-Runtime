import unittest

from app.core import RunRecord, RunStatus
from app.services import TemporalRunOrchestrator


class FakeTemporalRuntime:
    def __init__(self) -> None:
        self.mode = "sdk"
        self.reason = "available"
        self.target_hostport = "temporal:7233"
        self.namespace = "default"
        self.workflow_name = "emata_run_workflow"
        self.task_queue = "emata-runs"
        self.started = []
        self.signals = []

    def describe(self):
        return {
            "mode": self.mode,
            "target_hostport": self.target_hostport,
            "namespace": self.namespace,
            "workflow_name": self.workflow_name,
            "task_queue": self.task_queue,
            "reason": self.reason,
        }

    async def start_run_workflow(self, workflow_id: str, payload: dict) -> None:
        self.started.append({"workflow_id": workflow_id, "payload": payload})

    async def signal_run_workflow(self, workflow_id: str, signal_name: str, payload: dict) -> None:
        self.signals.append(
            {
                "workflow_id": workflow_id,
                "signal_name": signal_name,
                "payload": payload,
            }
        )


class TemporalRunOrchestratorTestCase(unittest.TestCase):
    def test_submit_run_starts_temporal_workflow(self) -> None:
        runtime = FakeTemporalRuntime()
        orchestrator = TemporalRunOrchestrator(runtime)
        run = RunRecord(
            id="run-123",
            organization_id="org-acme",
            workspace_id="workspace-finance",
            title="Sync ERP order",
            goal="Push approved order update.",
            requested_capability="erp.write",
            status=RunStatus.WAITING_APPROVAL,
            requested_by="user-admin",
            orchestrator_backend="temporal",
        )

        orchestrator.submit_run(run)

        self.assertEqual(len(runtime.started), 1)
        self.assertEqual(runtime.started[0]["workflow_id"], "run-123")
        self.assertTrue(runtime.started[0]["payload"]["requires_approval"])

    def test_approval_and_cancel_signal_running_workflow(self) -> None:
        runtime = FakeTemporalRuntime()
        orchestrator = TemporalRunOrchestrator(runtime)

        orchestrator.signal_approval("run-123", "approve")
        orchestrator.signal_cancel("run-123")

        self.assertEqual(
            runtime.signals,
            [
                {
                    "workflow_id": "run-123",
                    "signal_name": "approval",
                    "payload": {"decision": "approve"},
                },
                {
                    "workflow_id": "run-123",
                    "signal_name": "cancel",
                    "payload": {},
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
