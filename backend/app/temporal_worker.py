import asyncio
import os
from typing import Any, Dict

from app.integrations import TemporalRuntime
from app.temporal_workflow import EMATARunWorkflow, TEMPORAL_SDK_AVAILABLE, run_controlled_step


async def connect_temporal_client(
    client_cls: Any,
    target_hostport: str,
    namespace: str,
    max_attempts: int = 10,
    delay_seconds: float = 1.0,
):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await client_cls.connect(target_hostport, namespace=namespace)
        except Exception as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            await asyncio.sleep(delay_seconds)
    raise last_error


async def run_worker() -> Dict[str, str]:
    runtime = TemporalRuntime(
        target_hostport=os.getenv("EMATA_TEMPORAL_TARGET", "temporal:7233"),
        namespace=os.getenv("EMATA_TEMPORAL_NAMESPACE", "default"),
    )
    if not TEMPORAL_SDK_AVAILABLE:
        return {"status": "skipped", "reason": "temporalio_not_installed"}

    from temporalio.client import Client  # type: ignore
    from temporalio.worker import Worker  # type: ignore

    max_attempts = int(os.getenv("EMATA_TEMPORAL_CONNECT_RETRIES", "20"))
    delay_seconds = float(os.getenv("EMATA_TEMPORAL_CONNECT_DELAY_SECONDS", "1"))
    client = await connect_temporal_client(
        Client,
        runtime.target_hostport,
        runtime.namespace,
        max_attempts=max_attempts,
        delay_seconds=delay_seconds,
    )
    worker = Worker(
        client,
        task_queue=runtime.task_queue,
        workflows=[EMATARunWorkflow],
        activities=[run_controlled_step],
    )
    await worker.run()
    return {"status": "stopped", "reason": "worker_exited"}


if __name__ == "__main__":
    result = asyncio.run(run_worker())
    print(result)
