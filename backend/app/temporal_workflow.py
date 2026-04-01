from datetime import timedelta
from typing import Any, Dict

TEMPORAL_SDK_AVAILABLE = False

try:
    from temporalio import activity, workflow  # type: ignore

    TEMPORAL_SDK_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency path
    activity = None
    workflow = None


if TEMPORAL_SDK_AVAILABLE:

    def controlled_step_timeout() -> timedelta:
        return timedelta(seconds=30)

    @activity.defn(name="run_controlled_step")
    async def run_controlled_step(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "accepted",
            "step_type": payload.get("type", "unknown"),
            "payload": payload,
        }


    @workflow.defn(name="emata_run_workflow")
    class EMATARunWorkflow:
        def __init__(self) -> None:
            self.approval_payload: Dict[str, Any] | None = None
            self.cancel_requested = False

        @workflow.signal(name="approval")
        async def approval(self, payload: Dict[str, Any]) -> None:
            self.approval_payload = payload

        @workflow.signal(name="cancel")
        async def cancel(self) -> None:
            self.cancel_requested = True

        @workflow.run
        async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
            if payload.get("requires_approval"):
                await workflow.wait_condition(
                    lambda: self.approval_payload is not None or self.cancel_requested
                )
                if self.cancel_requested:
                    return {
                        "workflow_name": "emata_run_workflow",
                        "status": "canceled",
                    }
                if (self.approval_payload or {}).get("decision") == "reject":
                    return {
                        "workflow_name": "emata_run_workflow",
                        "status": "rejected",
                    }

            if self.cancel_requested:
                return {
                    "workflow_name": "emata_run_workflow",
                    "status": "canceled",
                }

            result = await workflow.execute_activity(
                run_controlled_step,
                payload,
                start_to_close_timeout=controlled_step_timeout(),
            )
            return {
                "workflow_name": "emata_run_workflow",
                "status": "completed",
                "result": result,
            }

else:

    def controlled_step_timeout() -> timedelta:
        return timedelta(seconds=30)

    async def run_controlled_step(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "skipped",
            "reason": "temporalio_not_installed",
            "payload": payload,
        }


    class EMATARunWorkflow:  # pragma: no cover - fallback placeholder
        pass
